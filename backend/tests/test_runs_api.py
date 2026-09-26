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
from app.agents.schemas import AGENT_ORDER, ANALYSTS
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
    def render_xyz_stub(raster, layer, **kwargs):
        kwargs.setdefault("tiles_dir", tmp_path / "tiles")
        return tiles.render_xyz(raster, layer, **kwargs)

    monkeypatch.setattr(assessment_module, "render_xyz", render_xyz_stub)
    write = probability.write
    monkeypatch.setattr(
        assessment_module.prob,
        "write",
        lambda pm, path=tmp_path / "probability.tif": write(pm, path),
    )
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
    baseline = client.get("/mountains/mount-rainier").json()
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
    assert set(running[:5]) == set(ANALYSTS)  # the fan-out reaches the stream as five starts
    done = [m["agent"] for m in agent_events if m["status"] == "done"]
    assert done[-2:] == ["synthesizer", "writer"]
    assert all(m["trace"]["route"]["provider"] in ("gemini", "grok") for m in agent_events)
    final = messages[-1]["run"]
    assert final["status"] == "done" and final["phase"] == "finished"
    assert final["message"].startswith("Finished in")
    assert final["rain"]["source"] == "fixture" and final["rain"]["past_72h_mm"] > 0

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done" and set(run["agents"]) == set(AGENT_ORDER)
    mountain = client.get("/mountains/mount-rainier").json()
    assert mountain["active_run_id"] is None
    assert mountain["last_analyzed_at"]
    if run["model_decision_eligible"]:
        assert mountain["active_hazard"]["run_id"] == run_id and mountain["active_hazard"]["id"] == run["hazard_id"]
        hazard = mountain["active_hazard"]
        assert hazard["what"]
        if hazard.get("bypass"):
            assert hazard["bypass"]["name"] == "Golden Gate Trail"
        assert mountain["current_risk_level"] == run["severity"]
    else:
        assert run["model_state"] == "UNCERTAIN"
        assert run["hazard_id"] is None and mountain["active_hazard"] is None
        assert mountain["current_risk_level"] == baseline["current_risk_level"]
    hero = next(t for t in mountain["trails"] if t["segments"])
    assert all(s["risk_level"] for s in hero["segments"])

    forecast_response = client.get("/forecast", params={"mountain_id": "mount-rainier", "trail_id": hero["id"]})
    forecast_sentence = None
    if run["model_decision_eligible"]:
        forecast = forecast_response.json()
        forecast_sentence = forecast["sentence"]
        assert forecast["run_id"] == run_id and forecast["level"] == run["severity"]
        assert forecast["sentence"] == run["agents"]["writer"]["payload"]["hiker"]
        if forecast.get("bypass"):
            assert forecast["bypass"]["name"] == "Golden Gate Trail"
        assert forecast["trail_name"] == hero["name"]
    else:
        assert forecast_response.status_code == 404

    # The advisory rides on the run and answers on its own endpoints, in memory and from the row.
    advisory = run["advisory"]
    assert advisory is not None and advisory["run_id"] == run_id
    assert client.get(f"/runs/{run_id}/advisory").json() == advisory
    assert client.get("/mountains/mount-rainier/advisory").json() == advisory
    assert len(advisory["avoid"]) == len(advisory["safe"]) == 3
    trails = {t["name"] for t in client.get("/mountains/mount-rainier").json()["trails"]}
    assert all(route["trail"] in trails for route in advisory["avoid"] + advisory["safe"])
    assert advisory["response"]["posture"] in ("all_clear", "watch", "advisory", "warning", "evacuate")
    assert advisory["severity"] == run["severity"]
    if forecast_sentence is not None:
        assert advisory["alert"]["hiker"] == forecast_sentence

    # Step 33: the same run is logged to previous_runs, tagged and split into the two sides of
    # the run, so the /history page has it after the process that ran it is gone.
    logged = client.get("/history", params={"slug": "mount-rainier"}).json()
    row = next(r for r in logged["runs"] if r["run_id"] == run_id)
    assert row["hazard_class"] in ("landslide", "debris_flow")
    if run["model_decision_eligible"]:
        assert row["hazard_type"] == hazard["type"]
    assert row["severity"] == run["severity"]
    assert {c["agent"] for c in row["llm_calls"]} == set(AGENT_ORDER)
    detail = client.get(f"/history/{run_id}").json()
    assert set(detail["agent_outputs"]) == set(AGENT_ORDER)
    if forecast_sentence is not None:
        assert detail["agent_outputs"]["writer"]["payload"]["hiker"] == forecast_sentence
    assert detail["advisory"] == advisory
    assert detail["model_method"] == run["method"]

    # A new process has no runs in memory: the finished run, and its advisory, come back from
    # the row instead.
    fresh = RunRegistry(providers={})
    runs_route.registry = fresh
    stored = client.get(f"/runs/{run_id}").json()
    assert stored["status"] == "done" and stored["agents"]["writer"]["payload"]["hiker"]
    assert follow(client, run_id)[0]["run"]["status"] == "done"
    assert client.get("/mountains/mount-rainier/advisory").json()["run_id"] == run_id


def test_advisory_404s_on_an_unknown_run_or_mountain(api):
    """No advisory is a 404, not a crash, and a static marker never has one."""
    client, _ = api
    assert client.get("/runs/2f1a0c9e-0000-4000-8000-000000000000/advisory").status_code == 404
    assert client.get("/runs/not-a-uuid/advisory").status_code == 404
    assert client.get("/mountains/mount-fuji/advisory").status_code == 404


def test_failed_run_keeps_the_last_hazard(api, monkeypatch):
    client, _ = api
    first = client.post("/mountains/mount-rainier/analyze").json()["run_id"]
    first_final = follow(client, first)[-1]["run"]
    first_hazard = client.get("/mountains/mount-rainier").json()["active_hazard"]
    monkeypatch.setenv("FAKE_LLM_FAIL", "gemini,grok")
    failed = client.post("/mountains/mount-rainier/analyze").json()["run_id"]
    final = follow(client, failed)[-1]["run"]
    assert final["status"] == "error"
    assert final["message"] == "Run failed at the Terrain step."
    assert final["failed_agent"] == "terrain" and "No provider" in final["error"]
    current_hazard = client.get("/mountains/mount-rainier").json()["active_hazard"]
    if first_final["model_decision_eligible"]:
        assert current_hazard["run_id"] == first
    else:
        assert first_hazard is None and current_hazard is None


def test_location_analyze_without_trails(api):
    """A catalog peak with no trail geometry still runs, and it does not invent routes.

    With the regional model artifacts built, the run's method and its advisory quote the
    model's live summit prediction; without them it falls back to the cell classifier.
    """
    from app.ml.geo_susceptibility import predict_summit

    client, _ = api
    started = client.post("/mountains/huascaran/analyze")
    assert started.status_code == 202
    final = follow(client, started.json()["run_id"])[-1]["run"]
    assert final["status"] == "done", final.get("error")
    geo = predict_summit("huascaran", -9.1219, -77.6047)
    if geo.get("available"):
        assert final["method"] == "regional terrain susceptibility (LightGBM)"
        assert final["advisory"]["model"]["map_max"] == geo["probability"]
        # Huascarán has no terrain window of its own: stand-in input, so the run is an advisory.
        assert geo["input_source"] == "placeholder_terrain_sample"
        assert final["advisory"]["model"]["is_stand_in"] is True
        assert final["needs_review"] is True
    else:
        assert final["method"] == "location cell classification"
    assert final["advisory"]["avoid"] == [] and final["advisory"]["safe"] == []
    assert "no trails" in final["agents"]["trail"]["summary"].lower()


def test_rejects(api):
    client, _ = api
    assert client.post("/mountains/nowhere/analyze").status_code == 404
    assert client.get("/runs/not-a-uuid").status_code == 404
    assert client.get(f"/runs/{uuid.uuid4()}").status_code == 404
    assert client.get("/forecast", params={"mountain_id": "nowhere"}).status_code == 404
    assert follow(client, str(uuid.uuid4()))[0]["kind"] == "error"
