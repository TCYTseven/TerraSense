"""Grouped folds never leak a storm, a year, or a cell; the fits and metrics behave."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import event_validate as ev  # noqa: E402


def _table(n_sets: int = 300, k: int = 4, seed: int = 0, beta=(1.5, 0.8)) -> pd.DataFrame:
    """Synthetic matched sets: the case is drawn from each set with conditional-logit weights."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sets):
        wy = 1990 + s // 12
        storm = f"storm_{wy}_{(s % 12) // 3}"
        cell = f"c{s % 25}"
        x = rng.uniform(-1, 1, (k + 1, 2))
        w = np.exp(x @ np.array(beta))
        case = rng.choice(k + 1, p=w / w.sum())
        for j in range(k + 1):
            sample_wy = wy if j == case else int(rng.integers(1981, 2024))
            rows.append({"cluster_id": f"set{s}", "storm_id": storm, "water_year": wy, "cell_id": cell,
                         "cell_lat": 46 + (s % 25) * 0.1, "cell_lon": -123 + (s % 5) * 0.4,
                         "sample_water_year": sample_wy, "label": int(j == case),
                         "rainfall_exceedance": x[j, 0], "moisture_index": x[j, 1]})
    return pd.DataFrame(rows)


def test_year_folds_never_split_a_year_storm_or_set() -> None:
    rows = _table()
    sets = rows.drop_duplicates("cluster_id").set_index("cluster_id")
    fold = ev.year_block_folds(sets, 5)
    assert fold.nunique() == 5
    by = sets.assign(fold=fold)
    assert (by.groupby("water_year").fold.nunique() == 1).all()
    assert (by.groupby("storm_id").fold.nunique() == 1).all()
    # Contiguous blocks: fold number never decreases as the water year increases.
    order = by.groupby("water_year").fold.first().sort_index()
    assert order.is_monotonic_increasing


@pytest.mark.parametrize("scheme", ["year", "region"])
def test_training_rows_never_touch_the_held_out_fold(scheme: str) -> None:
    rows = _table()
    sets = rows.drop_duplicates("cluster_id").set_index("cluster_id")
    fold_of_set = ev.year_block_folds(sets, 5) if scheme == "year" else ev.region_folds(sets, 5)
    for f in range(5):
        train, test = ev.train_test_masks(rows, fold_of_set, f, scheme)
        assert not (train & test).any()
        assert set(rows.cluster_id[train]).isdisjoint(rows.cluster_id[test])
        assert set(rows.storm_id[train]).isdisjoint(rows.storm_id[test]) or scheme == "region"
        if scheme == "year":
            held = set(rows.water_year[test])
            assert set(rows.sample_water_year[train]).isdisjoint(held)
            assert set(rows.water_year[train]).isdisjoint(held)
        else:
            assert set(rows.cell_id[train]).isdisjoint(rows.cell_id[test])
        # Every row of a held-out set is tested.
        assert rows[test].groupby("cluster_id").label.sum().eq(1).all()


def test_conditional_logit_recovers_known_weights() -> None:
    rows = _table(n_sets=3000, beta=(1.5, 0.8), seed=4)
    beta = ev.fit_clr(rows[ev.MODEL_B_TERMS].to_numpy(), pd.factorize(rows.cluster_id)[0], rows.label.to_numpy())
    assert beta[0] == pytest.approx(1.5, abs=0.15)
    assert beta[1] == pytest.approx(0.8, abs=0.15)


def test_handset_logit_is_the_live_formula() -> None:
    rows = pd.DataFrame({"rainfall_exceedance": [1.0, -1.0], "moisture_index": [0.5, -0.25],
                         "susceptibility": [np.nan, 0.9]})
    expected = [2.0 * 1.0 + 1.6 * 0.5, 7.0 * (0.9 - 0.75) + 2.0 * -1.0 + 1.6 * -0.25]
    assert ev.handset_logit(rows) == pytest.approx(expected)


def test_matched_concordance_counts_pairs_within_sets_only() -> None:
    rows = pd.DataFrame({"cluster_id": ["a", "a", "a", "b", "b"], "label": [1, 0, 0, 1, 0]})
    score = np.array([0.5, 0.4, 0.9, 0.1, 0.1])
    parts = ev.matched_concordance_parts(rows, score)
    assert parts.loc["a"].tolist() == [1.0, 2]
    assert parts.loc["b"].tolist() == [0.5, 1]


def test_ece_is_zero_for_perfect_calibration_and_positive_otherwise() -> None:
    y = np.array([0] * 80 + [1] * 20)
    assert ev.ece(y, np.full(100, 0.2)) == pytest.approx(0.0)
    assert ev.ece(y, np.full(100, 0.9)) == pytest.approx(0.7)


def test_weights_rule_needs_a_significant_brier_gain_and_no_ranking_loss() -> None:
    def boot(brier_ci, auc, conc=0.0):
        return {"delta_vs_handset_ci95": {"lr_model_b": {"delta_brier": brier_ci}},
                "delta_vs_handset_mean": {"lr_model_b": {"delta_roc_auc": auc, "delta_matched_concordance": conc}}}
    assert ev.weights_rule(boot([-0.02, -0.01], 0.001))[0]
    assert not ev.weights_rule(boot([-0.02, 0.001], 0.01))[0]
    assert not ev.weights_rule(boot([-0.02, -0.01], -0.002))[0]
    assert not ev.weights_rule(boot([-0.02, -0.01], 0.001, -0.003))[0]
