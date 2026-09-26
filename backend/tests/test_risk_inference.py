from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import lightgbm as lgb
import numpy as np

from app.ml import risk_inference
from app.ml.risk_contract import MODEL_FEATURES
from app.weather import HourlyRain


def test_calibrated_artifact_can_drive_high_risk_prediction(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "landslide_risk_lgbm.txt"
    metadata_path = tmp_path / "risk_model.json"
    calibration_path = tmp_path / "risk_calibration.json"
    rng = np.random.default_rng(12)
    x = np.zeros((80, len(MODEL_FEATURES)), dtype="float32")
    y = np.array([0] * 40 + [1] * 40, dtype="int8")
    x[40:, 0] = 1
    model = lgb.LGBMClassifier(n_estimators=40, num_leaves=7, min_child_samples=2, verbosity=-1, random_state=1)
    model.fit(x + rng.normal(0, 0.01, x.shape), y)
    model.booster_.save_model(str(model_path))

    distributions = {name: {"p01": -1.0, "p99": 2.0, "median": 0.5} for name in MODEL_FEATURES}
    metadata_path.write_text(json.dumps({
        "model_version": "test",
        "feature_names": list(MODEL_FEATURES),
        "selected_threshold": 0.5,
        "ood_threshold": 0.35,
        "abstention_band": 0.01,
        "feature_distributions": distributions,
        "validation": {"test": {"pr_auc": 0.9}},
        "training_date": "2026-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    calibration_path.write_text(json.dumps({"method": "platt", "coef": 8.0, "intercept": -4.0}), encoding="utf-8")

    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rain = HourlyRain([start + timedelta(hours=i) for i in range(96)], [1.0] * 96, 0, "gfs", start)
    monkeypatch.setattr(risk_inference, "RISK_MODEL_PATH", model_path)
    monkeypatch.setattr(risk_inference, "RISK_METADATA_PATH", metadata_path)
    monkeypatch.setattr(risk_inference, "RISK_CALIBRATION_PATH", calibration_path)
    monkeypatch.setattr(risk_inference, "try_hourly_rain", lambda *_args, **_kwargs: (rain, None))
    monkeypatch.setattr(risk_inference, "_static_features", lambda *_args: ({name: 1.0 for name in MODEL_FEATURES}, {"copernicus_dem": {"available": True}, "worldcover": {"available": True}, "soilgrids": {"available": True}}))
    monkeypatch.setattr(risk_inference, "hourly_dynamic_features", lambda *_args, **_kwargs: {name: 1.0 for name in MODEL_FEATURES})
    monkeypatch.setenv("LANDSLIDE_FORECAST_PROVIDER", "gfs")
    risk_inference._model_cache = None

    prediction = risk_inference.predict_location(46.8523, -121.7603)

    assert prediction.state == "HIGH_RISK"
    assert prediction.calibrated_probability is not None
    assert prediction.high_risk_threshold == 0.5
    assert prediction.window_end - prediction.window_start == timedelta(hours=72)
