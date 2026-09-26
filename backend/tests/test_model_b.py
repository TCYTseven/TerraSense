from datetime import UTC, datetime, timedelta

import numpy as np
import rasterio
from affine import Affine

from app.ml import model_b
from app.weather import HourlyRain


def _raster(path, values):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:32610",
        transform=Affine.translation(500000, 5200000) @ Affine.scale(30, -30),
        nodata=np.nan,
    ) as dst:
        dst.write(values.astype("float32"), 1)


def _rain(past_7d_mm=0.0, next_72h_mm=0.0):
    forecast_hours = model_b.FORECAST_WINDOW_HOURS
    values = [past_7d_mm / 168.0] * 168 + [next_72h_mm / forecast_hours] * forecast_hours
    start = datetime(2026, 9, 18, tzinfo=UTC)
    times = [start + timedelta(hours=i) for i in range(len(values))]
    return HourlyRain(times, values, 168, "fixture", start)


def test_run_preserves_grid_and_nodata_and_wet_rain_increases_risk(tmp_path, monkeypatch):
    values = np.array([[0.2, 0.8], [0.5, np.nan]], dtype="float32")
    path = tmp_path / "susceptibility.tif"
    _raster(path, values)
    monkeypatch.setattr(model_b, "SUSCEPTIBILITY_PATH", path)

    dry = model_b.run(None)
    wet = model_b.run(_rain(past_7d_mm=80.0, next_72h_mm=35.0))

    assert dry.probability.dtype == np.float32
    assert dry.probability.shape == values.shape
    assert dry.transform == Affine.translation(500000, 5200000) @ Affine.scale(30, -30)
    assert dry.crs == "EPSG:32610"
    assert np.isnan(dry.probability[1, 1])
    assert np.all(wet.probability[:1, :] > dry.probability[:1, :])
    assert np.isfinite(wet.probability[:1, :]).all()


def test_terrain_gates_the_rain_trigger(tmp_path, monkeypatch):
    """A saturating storm cannot make stable ground high risk, and a dry week keeps the map's steepest ground below high."""
    # 0.79 is about the highest calibrated susceptibility in the Rainier box.
    values = np.array([[0.0, 0.25, 0.79]], dtype="float32")
    path = tmp_path / "susceptibility.tif"
    _raster(path, values)
    monkeypatch.setattr(model_b, "SUSCEPTIBILITY_PATH", path)

    storm = model_b.run(_rain(past_7d_mm=500.0, next_72h_mm=500.0)).probability[0]
    dry = model_b.run(_rain()).probability[0]

    assert storm[0] < 0.2, "stable ground stays low in the worst storm"
    assert storm[2] > 0.7, "the most susceptible ground reaches extreme in a storm"
    assert storm[0] < storm[1] < storm[2]
    assert dry.max() < 0.45, "no ground reaches high without rain"


def test_rain_at_the_reference_thresholds_scales_terrain_odds_by_the_fitted_baseline(tmp_path, monkeypatch):
    values = np.array([[0.05, 0.25, 0.6]], dtype="float32")
    path = tmp_path / "susceptibility.tif"
    _raster(path, values)
    monkeypatch.setattr(model_b, "SUSCEPTIBILITY_PATH", path)
    rain = _rain(past_7d_mm=model_b.MOISTURE_THRESHOLD_7D_MM, next_72h_mm=model_b.RAINFALL_THRESHOLD_72H_MM)

    odds = values / (1 - values) * np.exp(model_b.W0 - model_b.TERRAIN_BASE_LOGIT)
    assert np.allclose(model_b.run(rain).probability, odds / (1 + odds), atol=1e-5)


def test_contributions_add_up_to_the_probability(tmp_path, monkeypatch):
    values = np.array([[0.62]], dtype="float32")
    path = tmp_path / "susceptibility.tif"
    _raster(path, values)
    monkeypatch.setattr(model_b, "SUSCEPTIBILITY_PATH", path)
    rain = _rain(past_7d_mm=30.0, next_72h_mm=40.0)

    terms = model_b.contributions(0.62, rain)
    logit = terms["terrain"] + terms["rain_baseline"] + terms["forecast_rain"] + terms["antecedent_moisture"]

    assert np.isclose(model_b.run(rain).probability[0, 0], 1 / (1 + np.exp(-logit)), atol=1e-6)
    assert terms["next_72h_mm"] == 40.0 and terms["threshold_72h_mm"] == model_b.RAINFALL_THRESHOLD_72H_MM


def test_rain_signals_are_bounded_and_missing_rain_is_explicit():
    dry = model_b.rain_signals(None)
    storm = model_b.rain_signals(_rain(past_7d_mm=500.0, next_72h_mm=500.0))

    assert (dry.rainfall_exceedance, dry.moisture_index) == (-1.0, -1.0)
    assert -1.0 <= storm.rainfall_exceedance <= 1.0
    assert -1.0 <= storm.moisture_index <= 1.0
    assert storm.next_72h_mm == 500.0
