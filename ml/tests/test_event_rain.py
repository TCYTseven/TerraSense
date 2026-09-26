"""Model B rain-signal parity with the backend, no-future leakage, and control exclusion."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import event_rain as er  # noqa: E402


def _backend_model_b():
    """Import backend/app/ml/model_b.py; the ML venv lacks dotenv and httpx, which it never calls here."""
    for name, attrs in (("dotenv", {"load_dotenv": lambda *a, **k: None}),
                        ("httpx", {"get": None, "HTTPStatusError": Exception, "HTTPError": Exception})):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            stub = types.ModuleType(name)
            stub.__dict__.update(attrs)
            sys.modules[name] = stub
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.ml import model_b
    from app.weather import HourlyRain
    return model_b, HourlyRain


def test_constants_match_backend() -> None:
    model_b, _ = _backend_model_b()
    assert er.RAINFALL_THRESHOLD_72H_MM == model_b.RAINFALL_THRESHOLD_72H_MM
    assert er.MOISTURE_THRESHOLD_7D_MM == model_b.MOISTURE_THRESHOLD_7D_MM
    assert (er.RAINFALL_WINDOW_HOURS, er.MOISTURE_WINDOW_HOURS) == (model_b.RAINFALL_WINDOW_HOURS,
                                                                    model_b.MOISTURE_WINDOW_HOURS)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("now_index", [168, 200, 230])
def test_rain_signals_match_backend(seed: int, now_index: int) -> None:
    model_b, HourlyRain = _backend_model_b()
    rng = np.random.default_rng(seed)
    precip = rng.gamma(0.4, 3.0 * (seed + 1), 312).round(1)
    start = datetime(2009, 1, 1, tzinfo=UTC)
    times = [start + timedelta(hours=i) for i in range(len(precip))]
    backend = model_b.rain_signals(HourlyRain(times, list(precip), now_index, "fixture", start))
    ours = er.model_b_signals(precip, now_index)
    for field in ("past_72h_mm", "next_72h_mm", "past_7d_mm", "rainfall_exceedance", "moisture_index"):
        assert ours[field] == pytest.approx(getattr(backend, field), abs=1e-9)


def _hourly(n: int = 288, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "precipitation": rng.gamma(0.5, 2.0, n), "temperature_2m": rng.normal(2, 3, n),
        "snowfall": rng.gamma(0.2, 0.5, n), "soil_moisture_0_to_7cm": rng.uniform(0.2, 0.4, n),
    }, index=pd.date_range("2009-01-01", periods=n, freq="h"))


def test_past_features_ignore_the_future() -> None:
    hourly = _hourly()
    now = 216
    changed = hourly.copy()
    changed.iloc[now:] = changed.iloc[now:] * 50 + 7
    a, b = er.rich_features(hourly, now), er.rich_features(changed, now)
    future = {"next_72h_mm", "rainfall_exceedance", "max_24h_next_72h_mm", "max_1h_next_72h_mm",
              "liquid_next_72h_mm", "rain_on_snow_next_72h_mm", "temp_mean_next_72h_c"}
    for key in a:
        if key in future:
            continue
        assert a[key] == pytest.approx(b[key], nan_ok=True), key
    assert a["next_72h_mm"] != b["next_72h_mm"]


def _synthetic_catalog():
    clusters = pd.DataFrame({
        "cluster_id": ["a#1", "a#2", "b#1"], "cell_id": ["a", "a", "b"],
        "cell_lat": [47.05, 47.05, 46.55], "cell_lon": [-122.05, -122.05, -121.55],
        "date": pd.to_datetime(["2007-12-03", "2009-01-07", "2009-01-07"]),
    })
    rng = np.random.default_rng(3)
    days = pd.to_datetime("1981-01-01") + pd.to_timedelta(rng.integers(0, 42 * 365, 400), unit="D")
    blockers = pd.DataFrame({"lat": 47.05 + rng.normal(0, 0.15, 400), "lon": -122.05 + rng.normal(0, 0.2, 400),
                             "start": days, "end": days + pd.to_timedelta(rng.integers(0, 3, 400), unit="D")})
    return clusters, blockers


def _assert_clear(controls: pd.DataFrame, cells: pd.DataFrame, blockers: pd.DataFrame) -> None:
    for c in controls.itertuples():
        near = blockers[er.haversine_km(c.cell_lat, c.cell_lon, blockers.lat.to_numpy(),
                                        blockers.lon.to_numpy()) <= er.EXCLUSION_RADIUS_KM]
        lo = near.start - pd.Timedelta(days=er.EXCLUSION_DAYS)
        hi = near.end + pd.Timedelta(days=er.EXCLUSION_DAYS)
        assert not ((lo <= c.day) & (c.day <= hi)).any(), (c.cluster_id, c.day)


def test_controls_avoid_every_nearby_landslide_and_never_repeat() -> None:
    clusters, blockers = _synthetic_catalog()
    # The case days themselves are landslides too.
    blockers = pd.concat([blockers, pd.DataFrame({"lat": clusters.cell_lat, "lon": clusters.cell_lon,
                                                  "start": clusters.date, "end": clusters.date})])
    controls = er.draw_controls(clusters, blockers, 6, 1980, 2023)
    assert len(controls) > 0
    _assert_clear(controls, clusters, blockers)
    case_year = controls.cluster_id.map(clusters.set_index("cluster_id").date.dt.year)
    assert (controls.day.dt.year != case_year).all()
    assert not controls.duplicated(["cell_id", "day"]).any()
    assert (controls.groupby("cluster_id").size() <= 6).all()


def test_control_month_matches_or_neighbors_case_month() -> None:
    clusters, blockers = _synthetic_catalog()
    controls = er.draw_controls(clusters, blockers, 4, 1980, 2023)
    case_month = controls.cluster_id.map(clusters.set_index("cluster_id").date.dt.month)
    gap = ((controls.day.dt.month - case_month + 6) % 12 - 6).abs()
    assert (gap <= 1).all()
    assert (gap[controls.month_offset == 0] == 0).all()


def test_case_windows_cover_every_lead_and_stay_short() -> None:
    days = list(pd.to_datetime(["2009-01-07", "2009-01-08", "2009-01-09", "2009-01-10", "2009-03-01"]))
    windows = er.case_windows(days)
    for d, w in windows.items():
        assert w.days <= er.MAX_REQUEST_DAYS
        assert pd.Timestamp(w.start) <= d - pd.Timedelta(days=er.WINDOW_BEFORE_DAYS)
        assert pd.Timestamp(w.end) >= d + pd.Timedelta(days=er.WINDOW_AFTER_DAYS - 1)


FEATURES = REPO_ROOT / "data" / "processed" / "events" / "features.parquet"
BLOCKERS = REPO_ROOT / "data" / "processed" / "events" / "exclusion_records.parquet"


@pytest.mark.skipif(not (FEATURES.is_file() and BLOCKERS.is_file()), reason="built table not present")
def test_built_table_controls_are_clear_of_landslides() -> None:
    table = pd.read_parquet(FEATURES)
    rows = table[table.lead_hours == 0]
    controls = rows[rows.role == "control"]
    _assert_clear(controls, rows, pd.read_parquet(BLOCKERS))
    assert not rows.sample_id.duplicated().any()
    assert (rows.groupby("cluster_id").label.sum() == 1).all()
