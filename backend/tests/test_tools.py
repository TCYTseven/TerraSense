"""Step 20: each tool returns facts for mount-rainier with no LLM call. Needs DATABASE_URL."""

import pytest

from app.agents import tools as tools_module
from app.agents.tools import RunContext, ToolError, call_tool, threshold_mm
from app.assessment import assess
from app.weather import get_hourly_rain

FIXTURE = "backend/fixtures/open_meteo_storm.json"


@pytest.fixture(scope="module")
def ctx(db_conn, monkeypatch_module):
    monkeypatch_module.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    rain = get_hourly_rain()
    return RunContext(run_id="test", slug="mount-rainier", mountain="Mount Rainier", peak=(46.8523, -121.7603),
                      assessment=assess(db_conn, rain=rain), rain=rain)


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as patch:
        yield patch


def test_raster_summary(ctx):
    call = call_tool(ctx, "get_raster_summary", mountain="mount-rainier")
    facts = call.result
    assert facts["method"] and facts["map"]["cells"] > 0
    zone = facts["hazard_zone"]
    assert zone["level"] in ("high", "extreme")
    assert zone["flagged_miles"]["start"] < zone["flagged_miles"]["end"]
    assert zone["nearby_junctions"], "the flagged miles should sit near a junction"


def test_trail_segments(ctx):
    facts = call_tool(ctx, "get_trail_segments", mountain="mount-rainier").result
    assert facts["trail"] == "Skyline Trail"
    assert facts["risk_by_mile"][0]["start_mile"] == 0
    assert facts["flagged"]["level"] in ("high", "extreme")
    if facts["bypass"]["exists"]:
        assert facts["bypass"]["name"]


def test_weather(ctx):
    facts = call_tool(ctx, "get_weather", lat=46.8523, lon=-121.7603).result
    assert facts["source"] == "fixture" and "SYNTHETIC" in facts["warning"]
    assert facts["mm"]["past_72h"] > 0
    assert facts["guzzetti_threshold_mm"]["72h"] == threshold_mm(72)


def test_weather_without_rain_raises(ctx):
    dry = RunContext(**{**ctx.__dict__, "rain": None, "rain_error": "Open-Meteo timed out"})
    with pytest.raises(ToolError, match="timed out"):
        call_tool(dry, "get_weather", lat=46.85, lon=-121.76)


def test_model_prediction_uses_cached_classifier_without_recomputing(ctx, monkeypatch):
    """Agent fan-out receives the coordinator's exact result, including its probability."""
    cached = {
        "state": "HIGH_RISK",
        "probability": 0.84,
        "probability_source": "calibrated_classifier",
        "calibrated_probability": 0.84,
        "high_risk_threshold": 0.81,
        "risk_level": "extreme",
        "reason_codes": [],
    }
    context = RunContext(**{**ctx.__dict__, "production_prediction": cached})
    monkeypatch.setattr(tools_module, "predict_location", lambda *_args, **_kwargs: pytest.fail("recomputed"))

    facts = call_tool(context, "get_model_prediction", mountain="mount-rainier").result

    assert facts["production_72h_classification"] == cached
    assert facts["decision_contract"]["decision_eligible"] is True


def test_model_prediction_without_rain_is_fail_closed(ctx, monkeypatch):
    context = RunContext(**{**ctx.__dict__, "rain": None, "production_prediction": None})
    monkeypatch.setattr(tools_module, "predict_location", lambda *_args, **_kwargs: pytest.fail("recomputed"))

    prediction = call_tool(context, "get_model_prediction", mountain="mount-rainier").result[
        "production_72h_classification"
    ]

    assert prediction["state"] == "UNCERTAIN"
    assert prediction["calibrated_probability"] is None
    assert "FORECAST_UNAVAILABLE" in prediction["reason_codes"]


def test_historical_events(ctx):
    facts = call_tool(ctx, "get_historical_events", lat=46.79, lon=-121.73, radius_km=5).result
    assert facts["radius_km"] == 5
    assert isinstance(facts["events"], list)


def test_thresholds():
    assert threshold_mm(24) == 13.0
    assert threshold_mm(72) == 24.1
