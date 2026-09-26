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
    values = [past_7d_mm / 168.0] * 168 + [next_72h_mm / 72.0] * 72
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


def test_rain_signals_are_bounded_and_missing_rain_is_explicit():
    dry = model_b.rain_signals(None)
    storm = model_b.rain_signals(_rain(past_7d_mm=500.0, next_72h_mm=500.0))

    assert (dry.rainfall_exceedance, dry.moisture_index) == (-1.0, -1.0)
    assert -1.0 <= storm.rainfall_exceedance <= 1.0
    assert -1.0 <= storm.moisture_index <= 1.0
    assert storm.next_72h_mm == 500.0
