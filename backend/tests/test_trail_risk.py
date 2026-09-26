"""GET /mountains/{slug}/trail-risk: the hill card's trails come from the map, not a fixture."""

import pytest
from fastapi.testclient import TestClient

from app import trailrisk
from app.agents.providers import DEFAULT_TIMEOUT_S, _timeout
from app.main import app
from app.risk import LIVE_SLUG, RISK_LEVELS
from app.routes import runs as runs_route
from app.runs import RunRegistry

STORM = "backend/fixtures/open_meteo_storm.json"


@pytest.fixture
def client(db_conn, monkeypatch):
    monkeypatch.setenv("OPEN_METEO_FIXTURE", STORM)
    monkeypatch.setattr(trailrisk, "_cached", {})
    with TestClient(app) as test_client:
        yield test_client


def test_the_live_mountain_gets_five_scored_trails(client):
    response = client.get(f"/mountains/{LIVE_SLUG}/trail-risk")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] in ("run", "preview") and body["method"]
    assert len(body["trails"]) == trailrisk.TOP_TRAILS
    assert body["level"] in RISK_LEVELS and 0 <= body["score"] <= 1
    assert body["score"] == pytest.approx(sum(t["score"] for t in body["trails"]) / len(body["trails"]), abs=1e-3)
    for trail in body["trails"]:
        assert trail["level"] in RISK_LEVELS and trail["primary_factor"]
        lon, lat = trail["point"]
        assert -121.93 <= lon <= -121.54 and 46.76 <= lat <= 46.96
    assert body["preventative"] and body["area_km2"] > 0


def test_a_static_marker_has_no_trail_map(client):
    static = client.get("/mountains").json()
    slug = next(m["slug"] for m in static if not m["is_live"])
    assert client.get(f"/mountains/{slug}/trail-risk").status_code == 404
    assert client.get("/mountains/no-such-peak/trail-risk").status_code == 404


def test_analyze_without_a_model_key_says_so(client, monkeypatch):
    registry = RunRegistry(providers={})
    monkeypatch.setattr(runs_route, "registry", registry)
    response = client.post(f"/mountains/{LIVE_SLUG}/analyze")
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


def test_a_bad_llm_timeout_falls_back_to_the_default():
    assert _timeout({"LLM_TIMEOUT_S": "ten"}) == DEFAULT_TIMEOUT_S
    assert _timeout({"LLM_TIMEOUT_S": "-1"}) == DEFAULT_TIMEOUT_S
    assert _timeout({"LLM_TIMEOUT_S": "40"}) == 40.0
