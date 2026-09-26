"""Adversarial tests for the trained susceptibility model contract."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import train_susceptibility as train  # noqa: E402


def training_table(rows_per_region: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(22)
    rows = []
    for region in range(4):
        for index in range(rows_per_region):
            slope = 10 + region * 4 + index * 0.3
            label = int(index % 3 == 0 or region == 3 and index == 1)
            rows.append({
                "elevation": 1000 + region * 30 + rng.normal(0, 2),
                "slope": slope,
                "aspect": np.nan if index == 0 else float(index * 20),
                "curvature": rng.normal(0, 1),
                "dist_drainage": 50 + index * 12,
                "landcover": 60 if label else 10,
                "twi": 5 + label * 3 + rng.normal(0, 0.2),
                "label": label,
                "region": region,
                "row": region * rows_per_region + index,
                "col": index,
            })
    return pd.DataFrame(rows)


def test_spatial_split_holds_out_whole_regions() -> None:
    table = training_table()

    test_regions = train.split_regions(table)
    test = table[table["region"].isin(test_regions)]

    assert test_regions
    assert set(test["region"]).isdisjoint(set(table["region"]) - set(test_regions))
    assert test["label"].sum() >= train.TEST_POSITIVE_SHARE * table["label"].sum()


def test_validate_table_rejects_bad_contracts() -> None:
    table = training_table()
    table.loc[1, "label"] = 2
    with pytest.raises(SystemExit, match="binary"):
        train.validate_table(table)

    duplicate = training_table()
    duplicate.loc[1, ["row", "col"]] = duplicate.loc[0, ["row", "col"]]
    with pytest.raises(SystemExit, match="duplicate"):
        train.validate_table(duplicate)


def test_train_returns_probabilities_and_feature_importance() -> None:
    model, metrics, importance = train.train(training_table())

    assert metrics["auc"] >= 0.5
    assert 0 <= metrics["precision_at_high"] <= 1
    assert set(metrics["features"]) == set(train.FEATURES)
    assert set(importance) == set(train.FEATURES)
    assert sum(importance.values()) == pytest.approx(1.0, abs=0.002)
    scores = model.predict_proba(train.as_frame(training_table()))[:, 1]
    assert np.isfinite(scores).all()
    assert ((scores >= 0) & (scores <= 1)).all()


def test_knowledge_index_is_bounded_and_water_is_zero() -> None:
    stack = np.ones((len(train.FEATURES), 4, 4), dtype="float32")
    stack[train.FEATURES.index("slope")] = np.array([
        [10, 20, 30, 40], [15, 25, 35, 45], [20, 30, 40, 50], [25, 35, 45, 55]
    ], dtype="float32")
    stack[train.FEATURES.index("landcover"), 0, 0] = 80

    index = train.knowledge_driven_index(stack)

    assert np.isfinite(index).all()
    assert float(index.min()) >= 0
    assert float(index.max()) <= 1
    assert index[0, 0] == 0
