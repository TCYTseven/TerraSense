"""Step 22: analyze, run status, and the live stream, end to end through the API.

Runs against a throwaway database made on the DATABASE_URL server (skipped when it cannot be
made) and the fake LLM APIs in-process. Tiles and the probability GeoTIFF go to a temp folder.
"""

import uuid

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from app import assessment as assessment_module
from app import db
from app.agents import pipeline as pipeline_module
from app.agents.providers import make_providers
from app.config import database_url
from app.main import app
from app.ml import probability, tiles
from app.routes import mountains as mountains_route
from app.routes import runs as runs_route
from app.runs import RunRegistry
from app.schema import apply_schema
from app.seed import main as seed

from .fake_llm import app as fake_llm

KEYS = {"GEMINI_API_KEY": "fake", "XAI_API_KEY": "fake", "GEMINI_BASE_URL": "http://fake-gemini",
        "XAI_BASE_URL": "http://fake-xai"}


@pytest.fixture(scope="module")
def scratch_url():
    """A new database with the schema and seed. Dropped afterwards."""
    try:
        base = database_url()
        admin = psycopg.connect(base, autocommit=True, connect_timeout=3)
    except (RuntimeError, psycopg.Error) as exc:
        pytest.skip(f"no database server: {exc}")
    name = f"terrasense_test_{uuid.uuid4().hex[:8]}"
    try:
        admin.execute(f'CREATE DATABASE "{name}"')
    except psycopg.Error as exc:
        admin.close()
        pytest.skip(f"cannot create a scratch database: {exc}")
    yield make_conninfo(base, dbname=name)
    db.close_pool()
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def api(scratch_url, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", scratch_url)
    monkeypatch.setenv("OPEN_METEO_FIXTURE", "backend/fixtures/open_meteo_storm.json")
    monkeypatch.setenv("FAKE_LLM_DELAY_S", "0.2")
    monkeypatch.delenv("FAKE_LLM_FAIL", raising=False)
    monkeypatch.setattr(pipeline_module, "RETRY_PAUSE_S", 0)
    db.close_pool()
    apply_schema()
    seed()
    # Rendered layers and the probability GeoTIFF go to the temp folder, not the repo.
    monkeypatch.setattr(assessment_module, "render_xyz",
                        lambda raster, layer: tiles.render_xyz(raster, layer, tiles_dir=tmp_path / "tiles"))
    write = probability.write
    monkeypatch.setattr(assessment_module.prob, "write", lambda pm: write(pm, tmp_path / "probability.tif"))
    registry = RunRegistry(providers=make_providers(KEYS, httpx.ASGITransport(app=fake_llm)))
    monkeypatch.setattr(runs_route, "registry", registry)
    monkeypatch.setattr(mountains_route, "registry", registry)
    with TestClient(app) as client:
        yield client, registry
    db.close_pool()


def follow(client, run_id):
    """Every message on the stream, until it closes."""
    messages = []
    with client.websocket_connect(f"/runs/{run_id}/stream") as ws:
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message.get("kind") == "run" and message["run"]["status"] != "running":
                return messages
            if message.get("kind") == "error":
                return messages


def test_analyze_streams_and_saves(api):
    client, _ = api
    started = client.post("/mountains/mount-rainier/analyze")
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    again = client.post("/mountains/mount-rainier/analyze")
    assert again.status_code == 200 and again.json()["run_id"] == run_id
    assert client.get("/mountains/mount-rainier").json()["active_run_id"] == run_id

    messages = follow(client, run_id)
    assert messages[0]["kind"] == "run"
    agent_events = [m for m in messages if "agent" in m]
    running = [m["agent"] for m in agent_events if m["status"] == "running"]
    assert set(running[:2]) == {"terrain", "weather"}
    done = [m["agent"] for m in agent_events if m["status"] == "done"]
    assert done[2:] == ["trail", "synthesizer", "writer"]
    assert all(m["trace"]["route"]["provider"] in ("gemini", "grok") for m in agent_events)
    final = messages[-1]["run"]
    assert final["status"] == "done" and final["phase"] == "finished"
    assert final["message"].startswith("Finished in")
    assert final["rain"]["source"] == "fixture" and final["rain"]["past_72h_mm"] > 0

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done" and set(run["agents"]) == {"terrain", "weather", "trail", "synthesizer", "writer"}
    mountain = client.get("/mountains/mount-rainier").json()
    assert mountain["active_run_id"] is None
    assert mountain["active_hazard"]["run_id"] == run_id and mountain["active_hazard"]["id"] == run["hazard_id"]
    assert mountain["active_hazard"]["what"] and mountain["active_hazard"]["bypass"]["name"] == "Golden Gate Trail"
    assert mountain["current_risk_level"] == run["severity"] and mountain["last_analyzed_at"]
    hero = next(t for t in mountain["trails"] if t["segments"])
    assert all(s["risk_level"] for s in hero["segments"])

    # A new process has no runs in memory: the finished run comes back from its row.
    fresh = RunRegistry(providers={})
    runs_route.registry = fresh
    stored = client.get(f"/runs/{run_id}").json()
    assert stored["status"] == "done" and stored["agents"]["writer"]["payload"]["hiker"]
    assert follow(client, run_id)[0]["run"]["status"] == "done"


def test_failed_run_keeps_the_last_hazard(api, monkeypatch):
    client, _ = api
    first = client.post("/mountains/mount-rainier/analyze").json()["run_id"]
    follow(client, first)
    monkeypatch.setenv("FAKE_LLM_FAIL", "gemini,grok")
    failed = client.post("/mountains/mount-rainier/analyze").json()["run_id"]
    final = follow(client, failed)[-1]["run"]
    assert final["status"] == "error"
    assert final["message"] == "Run failed at the Terrain step."
    assert final["failed_agent"] == "terrain" and "No provider" in final["error"]
    assert client.get("/mountains/mount-rainier").json()["active_hazard"]["run_id"] == first


def test_rejects(api):
    client, _ = api
    assert client.post("/mountains/huascaran/analyze").status_code == 409
    assert client.post("/mountains/nowhere/analyze").status_code == 404
    assert client.get("/runs/not-a-uuid").status_code == 404
    assert client.get(f"/runs/{uuid.uuid4()}").status_code == 404
    assert follow(client, str(uuid.uuid4()))[0]["kind"] == "error"
