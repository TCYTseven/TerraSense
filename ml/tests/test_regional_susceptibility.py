"""Leakage and contract tests for the regional susceptibility pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import build_regional_features as build  # noqa: E402
import train_regional_susceptibility as train  # noqa: E402


def brute_distance_to_blocks(x, y, blocks, block_m):
    """Distance from each point to the nearest block square, checking every block."""
    out = np.full(len(x), np.inf)
    for block in blocks:
        bx, by = divmod(block, 1_000_000)
        left, bottom = bx * block_m, by * block_m
        gx = np.maximum(0, np.maximum(left - x, x - (left + block_m)))
        gy = np.maximum(0, np.maximum(bottom - y, y - (bottom + block_m)))
        out = np.minimum(out, np.hypot(gx, gy))
    return out


@pytest.fixture
def points():
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.uniform(500_000, 600_000, n)
    y = rng.uniform(5_100_000, 5_200_000, n)
    labels = (rng.random(n) < 0.25).astype(int)
    return x, y, labels


def test_no_block_is_split_across_folds(points) -> None:
    x, y, labels = points
    blocks = train.block_ids(x, y)
    folds = train.assign_folds(blocks, labels)
    per_block = pd.DataFrame({"block": blocks, "fold": folds}).groupby("block")["fold"].nunique()
    assert (per_block == 1).all()
    assert set(np.unique(folds)) == set(range(train.N_FOLDS))
    positives = pd.Series(labels).groupby(folds).sum()
    assert positives.max() - positives.min() <= pd.Series(labels).groupby(blocks).sum().max()


def test_buffer_drops_every_training_row_near_a_test_block(points) -> None:
    x, y, labels = points
    blocks = train.block_ids(x, y)
    folds = train.assign_folds(blocks, labels)
    for k in range(train.N_FOLDS):
        train_mask, test_mask = train.split_with_buffer(x, y, blocks, folds, k)
        assert not (train_mask & test_mask).any()
        test_blocks = np.unique(blocks[test_mask])
        exact = brute_distance_to_blocks(x[train_mask], y[train_mask], test_blocks, train.BLOCK_M)
        assert exact.min() > train.CV_BUFFER_M
        # Nothing beyond the buffer outside the test fold was dropped.
        others = ~test_mask
        far = brute_distance_to_blocks(x[others], y[others], test_blocks, train.BLOCK_M) > train.CV_BUFFER_M
        assert np.array_equal(far, train_mask[others])


def test_block_distance_matches_brute_force(points) -> None:
    x, y, _ = points
    blocks = train.block_ids(x, y)
    chosen = set(np.unique(blocks)[::7].tolist())
    fast = train.distance_to_blocks(x, y, chosen)
    exact = brute_distance_to_blocks(x, y, chosen, train.BLOCK_M)
    near = exact < train.BLOCK_M
    assert np.allclose(fast[near], exact[near])


def test_negatives_respect_the_distance_rule_and_footprint() -> None:
    shape = (400, 400)
    rng = np.random.default_rng(1)
    seed_rows, seed_cols = rng.integers(0, 200, 60), rng.integers(0, 400, 60)
    distance = build.distance_to(seed_rows, seed_cols, shape)
    mapped = build.footprint(seed_rows, seed_cols, shape)
    candidates = (distance > build.NEGATIVE_EXCLUSION_M) & mapped
    picks = build.sample_negatives(candidates, 500, rng)
    rows, cols = np.unravel_index(picks, shape)
    brute = np.hypot((rows[:, None] - seed_rows[None]) * build.CELL_M,
                     (cols[:, None] - seed_cols[None]) * build.CELL_M).min(axis=1)
    assert (brute > build.NEGATIVE_EXCLUSION_M).all()
    assert mapped[rows, cols].all()
    assert len(np.unique(picks)) == len(picks)
    # The seeds only reach row 200, so the southern half of the grid is unmapped.
    step = build.FOOTPRINT_CELL_M // build.CELL_M
    assert not mapped[(200 // step + 1) * step:].any()


def test_thinning_keeps_one_positive_per_90_m_block() -> None:
    rows = np.array([0, 1, 2, 3, 3, 10, 11])
    cols = np.array([0, 2, 1, 0, 5, 10, 11])
    kept = build.thin(rows, cols)
    keys = set(zip(rows[kept] // 3, cols[kept] // 3, strict=True))
    assert len(keys) == len(kept) == 4


def test_positive_filter_excludes_low_confidence_fans_and_shoreline() -> None:
    records = pd.DataFrame({
        "Inventory": ["WA WGS"] * 5 + ["WA SDIC"],
        "Confidence": [8, 3, 2, 8, 8, 5],
        "LS_Type": ["Debris flow", None, "Debris flow", "fan", "Debris flow", "slide affected property"],
        "Info_Source": ["", "", "", "", "Marine shore landslides", ""],
    })
    assert build.training_positive_mask(records).tolist() == [True, True, False, False, False, False]


def test_calibrated_probabilities_stay_in_range_and_monotone() -> None:
    rng = np.random.default_rng(2)
    scores = rng.random(2000)
    labels = (rng.random(2000) < scores).astype(int)
    calibrator = train.fit_calibrator(scores, labels)
    grid = np.linspace(-0.5, 1.5, 201)
    out = calibrator.predict(grid)
    assert np.isfinite(out).all() and out.min() >= 0 and out.max() <= 1
    assert np.all(np.diff(out) >= 0)


def test_ece_is_zero_for_perfect_calibration_and_bounded() -> None:
    probs = np.repeat(np.linspace(0.05, 0.95, 10), 1000)
    labels = np.concatenate([np.r_[np.ones(int(p * 1000)), np.zeros(1000 - int(p * 1000))]
                             for p in np.linspace(0.05, 0.95, 10)])
    assert train.expected_calibration_error(labels, probs) < 1e-3
    assert 0 <= train.expected_calibration_error(labels, 1 - probs) <= 1


@pytest.mark.skipif(not build.TABLE_PATH.is_file(), reason="regional table not built")
def test_published_table_keeps_rainier_out_of_training() -> None:
    table = pd.read_parquet(build.TABLE_PATH)
    trainset, external = table[table["set"] == "train"], table[table["set"] == "external"]
    negatives = table[table["label"] == 0]
    assert (negatives["dist_any_record_m"] > build.NEGATIVE_EXCLUSION_M).all()
    rainier, width, height = build.utm_grid(build.RAINIER_BBOX, build.GRID_CRS)
    buffer = build.RAINIER_HOLDOUT_BUFFER_M
    left, top = rainier.c - buffer, rainier.f + buffer
    right, bottom = rainier.c + width * build.CELL_M + buffer, rainier.f - height * build.CELL_M - buffer
    inside = trainset["x"].between(left, right) & trainset["y"].between(bottom, top)
    assert not inside.any()
    assert external["x"].between(rainier.c, rainier.c + width * build.CELL_M).all()
    assert not table.duplicated(["row", "col"]).any()
    assert (trainset.groupby("label").size()[0] == build.NEGATIVES_PER_POSITIVE * trainset["label"].sum())
