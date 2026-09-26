"""The pipeline end to end against the fake LLM APIs in-process. Needs DATABASE_URL.

The shape under test is the fan-out: five analysts start together and finish before the
Synthesizer starts, and the Synthesizer's routes and ranger response survive the code's checks.
"""

import asyncio

import httpx
import pytest

from app.agents import pipeline as pipeline_module
from app.agents import advisory as guards
from app.agents.pipeline import Pipeline, writer_problems
from app.agents.schemas import AvoidRoute, SafeRoute
from app.agents.providers import make_providers
from app.agents.router import Router
from app.agents.schemas import AGENT_ORDER, ANALYSTS, AlertDraft
from app.agents.tools import RunContext
from app.assessment import assess, mile_text
from app.weather import get_hourly_rain

from .conftest import storm_rain
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
    monkeypatch.delenv("FAKE_LLM_BAD_ROUTES", raising=False)
    monkeypatch.setattr(pipeline_module, "RETRY_PAUSE_S", 0)
    return monkeypatch


@pytest.fixture(scope="module")
def assessment(db_conn):
    return assess(db_conn, rain=storm_rain())


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
    for event in events:
        assert event.trace is not None and event.trace.route.reason
    finals = {e.agent: e for e in events if e.status == "done"}
    assert finals["terrain"].trace.route.provider == "gemini"
    assert finals["trail"].trace.route.provider == "gemini"  # fast default (LLM_USE_GROK off)
    assert finals["writer"].trace.route.provider == "gemini"
    assert finals["terrain"].trace.thoughts and finals["terrain"].trace.tools
    assert finals["terrain"].payload["hazard_zone"]["max_probability"] == assessment.zone.max_probability
    final = result.final
    order = ["low", "moderate", "high", "extreme"]
    levels = [order.index(finals[a].payload["severity"]) for a in ("weather", "trail", "history", "routes")] + \
        [order.index(finals["terrain"].payload["hazard_zone"]["severity"])]
    assert min(levels) <= order.index(final.severity) <= max(levels)
    assert final.ranger_title.startswith(("Debris flow risk", "Landslide risk", "Advisory."))
    assert assessment.flagged is not None
    assert mile_text(assessment.flagged.start_mile, assessment.flagged.end_mile) in final.ranger_title
    if assessment.bypass:
        assert assessment.bypass.name in final.hiker
    assert len(final.hiker.split()) <= 25
    assert 0 <= final.confidence <= 1
    assert any("Confidence" in c for c in finals["synthesizer"].trace.checks)


def test_the_analysts_run_together(fake_env, assessment):
    """Every analyst starts before any of them finishes, and none starts after the Synthesizer."""
    _, events = run_pipeline(assessment)
    order = [(e.agent, e.status) for e in events]
    started = [agent for agent, status in order if status == "running"]
    assert started[:len(ANALYSTS)] == list(ANALYSTS)  # all five are in flight before the first answer
    first_done = next(i for i, (_, status) in enumerate(order) if status == "done")
    assert first_done >= len(ANALYSTS), "an analyst finished before the last one started"
    # The two tail agents run only once the fan-out is in: they read what the analysts produced.
    assert [agent for agent, status in order if status == "done"][-2:] == ["synthesizer", "writer"]


def test_every_agent_reads_the_model_prediction(fake_env, assessment):
    """The ML output is the source of truth, so every analyst fetches it before its model call."""
    _, events = run_pipeline(assessment)
    for agent in ANALYSTS:
        trace = next(e for e in events if e.agent == agent and e.status == "done").trace
        assert trace.tools[0].name == "get_model_prediction", agent
        assert trace.tools[0].result["role"].startswith("SOURCE OF TRUTH")


def test_the_advisory_is_grounded_in_the_catalog(fake_env, assessment):
    """Three routes a side, all real trails, none on both lists, and a posture the severity allows."""
    result, _ = run_pipeline(assessment)
    advisory = result.final.advisory
    catalog = {score.name: score for score in assessment.trail_scores}

    assert len(advisory.avoid) == len(advisory.safe) == 3
    named = [route.trail for route in advisory.avoid + advisory.safe]
    assert len(set(named)) == 6, "a trail appears on both lists"
    for route in advisory.avoid + advisory.safe:
        assert route.trail in catalog, f"{route.trail} is not a mapped trail"
        # The numbers are the map's, never the model's.
        assert route.max_probability == catalog[route.trail].max_probability
        assert route.level == catalog[route.trail].level
        assert route.reason and route.guidance
    for route in advisory.safe:
        assert route.max_probability <= min(r.max_probability for r in advisory.avoid)

    response = advisory.response
    low, high = guards.POSTURE_RANGE[advisory.severity]
    assert guards.posture_rank(low) <= response.posture_rank <= guards.posture_rank(high)
    plow, phigh = guards.PRIORITY_RANGE[response.posture]
    assert guards.priority_rank(plow) <= response.priority_rank <= guards.priority_rank(phigh)
    assert "emergency_broadcast" not in response.channels or response.posture == "evacuate"
    assert 2 <= len(response.actions) <= 5
    assert advisory.analysis and advisory.model.method == assessment.method
    assert set(advisory.agents) == set(AGENT_ORDER)


def test_an_invented_route_is_rejected_and_replaced(fake_env, assessment, monkeypatch):
    """A trail the map says nothing about never reaches the advisory, even if the model insists."""
    from app.agents import advisory as guards_module

    assert guards_module.route_problems(
        [AvoidRoute(trail="Mordor Ridge Trail", reason="r", instead="i")] * 3,
        [SafeRoute(trail="Rampart Ridge Trail", reason="r", caution="c")] * 3,
        assessment.trail_scores,
    ), "an unmapped trail should be a problem"

    monkeypatch.setenv("FAKE_LLM_BAD_ROUTES", "1")
    result, _ = run_pipeline(assessment)
    assert result.status == "done", result.error
    catalog = {score.name for score in assessment.trail_scores}
    assert all(route.trail in catalog for route in result.final.advisory.avoid + result.final.advisory.safe)


def test_gemini_down_falls_back_to_grok(fake_env, assessment):
    fake_env.setenv("FAKE_LLM_FAIL", "gemini")
    result, events = run_pipeline(assessment)
    assert result.status == "done", result.error
    terrain = next(e for e in events if e.agent == "terrain" and e.status == "done").trace
    assert [a.provider for a in terrain.attempts] == ["gemini", "gemini", "grok"]
    assert [a.ok for a in terrain.attempts] == [False, False, True]
    trail = next(e for e in events if e.agent == "trail" and e.status == "done").trace
    assert "grok" in [a.provider for a in trail.attempts]
    assert trail.attempts[-1].ok


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
    # The other analysts were already in flight, so they finish. Nothing downstream of the
    # fan-out runs: there is no decision to make from an incomplete set of reports.
    assert not any(e.agent in ("synthesizer", "writer") for e in events)
    assert {e.agent for e in events if e.status == "done"} == set(ANALYSTS) - {"weather"}


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


def test_agent_order_is_the_panel_order():
    assert AGENT_ORDER == ("terrain", "weather", "trail", "history", "routes", "synthesizer", "writer")
    assert ANALYSTS == AGENT_ORDER[:5]
