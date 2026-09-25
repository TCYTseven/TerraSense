"""Step 21: the five agents end to end, against the fake LLM APIs in-process. Needs DATABASE_URL."""

import asyncio

import httpx
import pytest

from app.agents import pipeline as pipeline_module
from app.agents.pipeline import Pipeline, writer_problems
from app.agents.providers import make_providers
from app.agents.router import Router
from app.agents.schemas import AGENT_ORDER, AlertDraft
from app.agents.tools import RunContext
from app.assessment import assess
from app.weather import get_hourly_rain

from .fake_llm import app as fake_llm

FIXTURE = "backend/fixtures/open_meteo_storm.json"
KEYS = {"GEMINI_API_KEY": "fake", "XAI_API_KEY": "fake", "GEMINI_BASE_URL": "http://fake-gemini",
        "XAI_BASE_URL": "http://fake-xai"}


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("FAKE_LLM_DELAY_S", "0")
    monkeypatch.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    monkeypatch.delenv("FAKE_LLM_FAIL", raising=False)
    monkeypatch.delenv("FAKE_LLM_BAD_WRITER", raising=False)
    monkeypatch.setattr(pipeline_module, "RETRY_PAUSE_S", 0)
    return monkeypatch


@pytest.fixture(scope="module")
def assessment(db_conn):
    return assess(db_conn)


def run_pipeline(assessment, env=KEYS, rain=True):
    rain_data = get_hourly_rain() if rain else None
    ctx = RunContext(run_id="test", slug="mount-rainier", mountain="Mount Rainier", peak=(46.8523, -121.7603),
                     assessment=assessment, rain=rain_data, rain_error=None if rain else "Open-Meteo timed out")
    providers = make_providers(env, httpx.ASGITransport(app=fake_llm))
    events = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(Pipeline(ctx, Router(providers, env=env), providers, emit).run())
    return result, events


def test_full_run(fake_env, assessment):
    result, events = run_pipeline(assessment)
    assert result.status == "done", result.error
    assert [e.agent for e in events[:2]] == ["terrain", "weather"] and {e.status for e in events[:2]} == {"running"}
    done = [e.agent for e in events if e.status == "done"]
    assert sorted(done[:2]) == ["terrain", "weather"] and done[2:] == ["trail", "synthesizer", "writer"]
    for event in events:
        assert event.trace is not None and event.trace.route.reason
    finals = {e.agent: e for e in events if e.status == "done"}
    assert finals["terrain"].trace.route.provider == "gemini"
    assert finals["trail"].trace.route.provider == "grok"  # the bypass crosses extreme ground
    assert finals["writer"].trace.route.provider == "grok"
    assert finals["terrain"].trace.thoughts and finals["terrain"].trace.tools
    assert finals["terrain"].payload["hazard_zone"]["max_probability"] == assessment.zone.max_probability
    final = result.final
    order = ["low", "moderate", "high", "extreme"]
    levels = [order.index(finals[a].payload["severity"]) for a in ("weather", "trail")] + \
        [order.index(finals["terrain"].payload["hazard_zone"]["severity"])]
    assert min(levels) <= order.index(final.severity) <= max(levels)
    assert final.ranger_title.startswith("Debris flow risk") or final.ranger_title.startswith("Advisory.")
    assert "Skyline Trail mile 4.6 to 4.9" in final.ranger_title
    assert "Golden Gate Trail" in final.hiker and len(final.hiker.split()) <= 25
    assert 0 <= final.confidence <= 1
    assert any("Confidence" in c for c in finals["synthesizer"].trace.checks)


def test_gemini_down_falls_back_to_grok(fake_env, assessment):
    fake_env.setenv("FAKE_LLM_FAIL", "gemini")
    result, events = run_pipeline(assessment)
    assert result.status == "done", result.error
    terrain = next(e for e in events if e.agent == "terrain" and e.status == "done").trace
    assert [a.provider for a in terrain.attempts] == ["gemini", "gemini", "grok"]
    assert [a.ok for a in terrain.attempts] == [False, False, True]
    trail = next(e for e in events if e.agent == "trail" and e.status == "running").trace
    assert trail.route.provider == "grok"


def test_writer_repair(fake_env, assessment):
    fake_env.setenv("FAKE_LLM_BAD_WRITER", "1")
    result, events = run_pipeline(assessment)
    assert result.status == "done"
    writer = next(e for e in events if e.agent == "writer" and e.status == "done").trace
    assert [(a.ok, a.repair) for a in writer.attempts] == [(False, False), (True, True)]
    assert "words" in writer.attempts[0].error and "number" in writer.attempts[0].error
    assert len(result.final.hiker.split()) <= 25


def test_no_rain_fails_at_weather(fake_env, assessment):
    result, events = run_pipeline(assessment, rain=False)
    assert result.status == "error" and result.failed_agent == "weather"
    assert "timed out" in result.error
    assert not any(e.agent in ("trail", "synthesizer", "writer") for e in events)


def test_no_keys_fail_clearly(fake_env, assessment):
    result, _ = run_pipeline(assessment, env={})
    assert result.status == "error" and "GEMINI_API_KEY or XAI_API_KEY" in result.error


def test_writer_problems_catch_the_copy_rules():
    draft = AlertDraft(
        ranger_body="Debris flow risk on the trail.",
        hiker="With a 0.96 probability the model says the slopes above the Skyline Trail may slide soon.",
        what="A debris flow zone.",
        why="Rain.",
        how_to_avoid="Go around.",
        reasoning=["a", "b"],
    )
    problems = writer_problems(draft, "Skyline Trail", "Golden Gate Trail", flagged=True, needs_review=True)
    text = " ".join(problems)
    for expected in ("number", "probability", "Golden Gate", "ranger_body must name", "what must name",
                     "Advisory", "Confirm on site"):
        assert expected in text


def test_agent_order_is_the_spec_order():
    assert AGENT_ORDER == ("terrain", "weather", "trail", "synthesizer", "writer")
