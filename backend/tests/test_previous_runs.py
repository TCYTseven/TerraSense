"""Step 33: the run history log.

The pure part (tagging, flattening, token totals) needs no database. The round trip writes a
run to previous_runs on the DATABASE_URL server and reads it back through the /history routes,
and skips when no database answers.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import previous_runs

STARTED = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def make_run(**overrides):
    """A finished run's view, the shape app.runs._store_run hands to previous_runs.record."""
    run = {
        "id": str(uuid.uuid4()),
        "mountain_slug": "mount-rainier",
        "status": "done",
        "phase": "finished",
        "message": "Finished in 28 s.",
        "started_at": STARTED.isoformat(),
        "finished_at": (STARTED + timedelta(seconds=28)).isoformat(),
        "elapsed_s": 28.4,
        "hazard_id": str(uuid.uuid4()),
        "severity": "high",
        "needs_review": False,
        "method": "model b",
        "rain": {"source": "fixture", "as_of": STARTED.isoformat(),
                 "past_72h_mm": 91.0, "next_24h_mm": 40.0},
        "error": None,
        "failed_agent": None,
        "agents": {
            "terrain": {
                "run_id": "r", "agent": "terrain", "status": "done", "summary": "Channelized.",
                "payload": {"type": "debris_flow", "severity": "high"},
                "trace": {
                    "route": {"provider": "gemini", "model": "gemini-3.8-flash",
                              "label": "Gemini 3.8 Flash", "tier": "fast", "reason": "fast tier",
                              "rules": [], "fallback": ["grok"], "available": {}},
                    "attempts": [{"provider": "gemini", "model": "gemini-3.8-flash", "ok": True,
                                  "latency_ms": 900, "error": None, "repair": False}],
                    "output": {"type": "debris_flow", "severity": "high"},
                    "reasoning": ["slope is steep", "the hollow is channelized"],
                    "latency_ms": 900,
                    "usage": {"input_tokens": 1200, "output_tokens": 300, "reasoning_tokens": 50},
                },
            },
            "writer": {
                "run_id": "r", "agent": "writer", "status": "done", "summary": "Copy written.",
                "payload": {"hiker": "Turn back at mile 3."},
                "trace": {
                    "route": {"provider": "grok", "model": "grok-4.3", "label": "Grok 4.3",
                              "tier": "strong", "reason": "stakes", "rules": [],
                              "fallback": [], "available": {}},
                    "attempts": [], "latency_ms": 1500,
                    "usage": {"input_tokens": 800, "output_tokens": 200},
                },
            },
        },
        "advisory": {
            "run_id": "r", "mountain_slug": "mount-rainier", "mountain": "Mount Rainier",
            "generated_at": STARTED.isoformat(), "severity": "high", "confidence": 0.72,
            "needs_review": False, "summary": "Debris flow across miles 3 to 5.",
            "analysis": "The rain loaded an already wet hollow.",
            "hazard": {"type": "debris_flow", "severity": "high", "place": "Kautz Creek"},
            "avoid": [], "safe": [],
            "response": {"posture": "warning", "priority": "urgent",
                         "recommended_action": "close", "headline": "Close Kautz Creek."},
            "conditions": {"source": "fixture", "snowfall_next_72h_cm": 0.0,
                           "temp_max_next_72h_c": 9.0},
            "model": {"method": "model b", "is_stand_in": False, "note": "",
                      "map_max": 0.81, "map_mean": 0.22, "share_at_high": 0.31},
            "alert": {}, "agents": {"terrain": {"label": "Terrain Analyst", "severity": "high"}},
        },
    }
    run.update(overrides)
    return run


MOUNTAIN = {"id": None, "name": "Mount Rainier", "lat": 46.8523, "lon": -121.7603,
            "elevation_m": 4392}


# --- tagging -------------------------------------------------------------------------------


@pytest.mark.parametrize("hazard_type,expected", [
    ("landslide", "landslide"),
    ("debris_flow", "debris_flow"),
    ("snow_avalanche", "avalanche"),
    (None, "unknown"),
    ("mudslide", "unknown"),
])
def test_classify_hazard(hazard_type, expected):
    assert previous_runs.classify_hazard(hazard_type) == expected


def test_snow_driven_needs_both_signals():
    assert previous_runs.is_snow_driven({"snowfall_next_72h_cm": 25.0, "temp_max_next_72h_c": -3.0})
    # Warm air: the snow will not hold.
    assert not previous_runs.is_snow_driven({"snowfall_next_72h_cm": 25.0, "temp_max_next_72h_c": 6.0})
    # A source that never carried snow must not be guessed either way.
    assert not previous_runs.is_snow_driven({"temp_max_next_72h_c": -3.0})
    assert not previous_runs.is_snow_driven(None)


# --- flattening ----------------------------------------------------------------------------


def test_build_row_tags_the_hazard_the_agents_and_the_model():
    row = previous_runs.build_row(make_run(), MOUNTAIN)

    assert row["hazard_class"] == "debris_flow"
    assert row["hazard_type"] == "debris_flow"
    assert row["snow_driven"] is False
    assert row["severity"] == "high"
    assert row["posture"] == "warning"
    assert row["recommended_action"] == "close"
    assert row["model_method"] == "model b"
    assert row["model_max_probability"] == 0.81
    assert row["mountain_name"] == "Mount Rainier"

    # Both model calls are logged with who answered, and the tokens are summed over the run.
    calls = row["llm_calls"].obj
    assert {c["agent"] for c in calls} == {"terrain", "writer"}
    assert {c["provider"] for c in calls} == {"gemini", "grok"}
    assert row["llm_usage"].obj == {"input_tokens": 2000, "output_tokens": 500,
                                    "reasoning_tokens": 50, "calls": 2}

    # Each agent's whole event and trace survives, raw model JSON included.
    agents = row["agent_outputs"].obj
    assert agents["terrain"]["trace"]["output"] == {"type": "debris_flow", "severity": "high"}


def test_build_row_falls_back_to_the_terrain_agent_when_there_is_no_advisory():
    """A run that failed after terrain and before the synthesizer still gets its tag."""
    run = make_run(status="error", advisory=None, severity=None,
                   error="Run failed at the Synthesizer step.", failed_agent="synthesizer")
    row = previous_runs.build_row(run, MOUNTAIN)

    assert row["hazard_class"] == "debris_flow"
    assert row["status"] == "error"
    assert row["failed_agent"] == "synthesizer"
    assert row["advisory"] is None
    assert row["model_method"] == "model b"  # from the run's own method


def test_build_row_survives_a_run_that_failed_before_any_agent():
    run = make_run(status="error", advisory=None, agents={}, severity=None, method=None,
                   rain=None, hazard_id=None, error="Database unavailable")
    row = previous_runs.build_row(run, MOUNTAIN)

    assert row["hazard_class"] == "unknown"
    assert row["hazard_type"] is None
    assert row["llm_calls"].obj == []
    assert row["llm_usage"].obj["calls"] == 0


# --- the round trip ------------------------------------------------------------------------


@pytest.fixture
def logged_run(db_conn):
    """Write one run to previous_runs on the real database, then remove it."""
    from app.schema import apply_schema

    apply_schema()
    run = make_run()
    previous_runs.record(run, MOUNTAIN)
    yield run
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM previous_runs WHERE run_id = %s", (run["id"],))
    db_conn.commit()


def test_history_routes_serve_the_logged_run(logged_run):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        page = client.get("/history", params={"slug": "mount-rainier", "limit": 50}).json()
        row = next(r for r in page["runs"] if r["run_id"] == logged_run["id"])

        assert row["hazard_class"] == "debris_flow"
        assert row["severity"] == "high"
        assert row["llm_usage"]["calls"] == 2
        assert page["stats"]["runs"] >= 1

        # The detail carries the payloads the list leaves out.
        detail = client.get(f"/history/{logged_run['id']}").json()
        assert detail["agent_outputs"]["terrain"]["trace"]["route"]["provider"] == "gemini"
        assert detail["advisory"]["summary"] == "Debris flow across miles 3 to 5."
        assert detail["run"]["message"] == "Finished in 28 s."

        # The filters narrow the list.
        assert client.get("/history", params={"hazard_class": "avalanche"}).json()["total"] == 0
        assert client.get("/history", params={"hazard_class": "debris_flow"}).json()["total"] >= 1


def test_recording_the_same_run_twice_updates_one_row(logged_run, db_conn):
    previous_runs.record(make_run(id=logged_run["id"], severity="extreme"), MOUNTAIN)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), max(severity) FROM previous_runs WHERE run_id = %s",
            (logged_run["id"],),
        )
        count, severity = cur.fetchone()
    assert (count, severity) == (1, "extreme")
