"""Metrics, validation-only thresholds, calibrators, and shift statistics for geographic validation.

Pure functions with no file access, shared by `geo_validate.py` and `combined_validate.py`.

Ranking (ROC-AUC, PR-AUC, lift), calibration (Brier, ECE), and decisions at a threshold
(precision, recall, F1, confusion counts) are reported as separate dimensions. Accuracy is never
reported alone: with a 1:3 design a model that flags nothing scores 0.75.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, precision_recall_curve, roc_auc_score

ECE_BINS = 10
PSI_BINS = 10
PROB_CLIP = 1e-6
# Validation-only operating points: a target is met by the threshold on the validation scores
# that keeps the most recall (precision targets) or the most precision (recall targets).
PRECISION_TARGETS = (0.60, 0.70, 0.80)
RECALL_TARGETS = (0.50, 0.60, 0.70)
SUMMARY_STATS = ("mean", "median", "std", "min", "max", "n")


# --- ranking, calibration, confusion -----------------------------------------------------------

def prevalence(labels) -> float:
    labels = np.asarray(labels)
    return float(labels.mean()) if labels.size else float("nan")


def both_classes(labels) -> bool:
    labels = np.asarray(labels)
    return labels.size > 0 and labels.min() != labels.max()


def expected_calibration_error(labels, probs, bins: int = ECE_BINS) -> float:
    """Weighted mean |observed rate - mean probability| over equal-width probability bins."""
    labels, probs = np.asarray(labels, dtype=float), np.asarray(probs, dtype=float)
    index = np.minimum((probs * bins).astype(int), bins - 1)
    total = 0.0
    for b in range(bins):
        in_bin = index == b
        if in_bin.any():
            total += in_bin.mean() * abs(labels[in_bin].mean() - probs[in_bin].mean())
    return float(total)


def reliability_rows(labels, probs, bins: int = ECE_BINS) -> list[dict]:
    labels, probs = np.asarray(labels, dtype=float), np.asarray(probs, dtype=float)
    index = np.minimum((probs * bins).astype(int), bins - 1)
    rows = []
    for b in range(bins):
        in_bin = index == b
        if in_bin.any():
            rows.append({"bin_low": b / bins, "bin_high": (b + 1) / bins, "n": int(in_bin.sum()),
                         "mean_probability": float(probs[in_bin].mean()),
                         "observed_rate": float(labels[in_bin].mean())})
    return rows


def confusion(labels, scores, threshold: float) -> dict:
    """Counts and rates for flagging scores >= threshold."""
    labels = np.asarray(labels).astype(int)
    flagged = np.asarray(scores) >= threshold
    tp = int((flagged & (labels == 1)).sum())
    fp = int((flagged & (labels == 0)).sum())
    fn = int((~flagged & (labels == 1)).sum())
    tn = int((~flagged & (labels == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    specificity = tn / (tn + fp) if tn + fp else float("nan")
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return {"threshold": float(threshold), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "specificity": specificity, "f1": f1,
            "share_flagged": float(flagged.mean()) if flagged.size else float("nan")}


def ranking_metrics(labels, scores) -> dict:
    """ROC-AUC, PR-AUC, prevalence and lift = PR-AUC / prevalence. NaN when one class is missing."""
    labels, scores = np.asarray(labels).astype(int), np.asarray(scores, dtype=float)
    base = prevalence(labels)
    out = {"n": int(labels.size), "positives": int(labels.sum()), "prevalence": base,
           "roc_auc": float("nan"), "pr_auc": float("nan"), "lift": float("nan")}
    if both_classes(labels):
        out["roc_auc"] = float(roc_auc_score(labels, scores))
        out["pr_auc"] = float(average_precision_score(labels, scores))
        out["lift"] = out["pr_auc"] / base
    return out


def probability_metrics(labels, probs) -> dict:
    """Brier, log loss and ECE; only meaningful for scores that claim to be probabilities."""
    labels, probs = np.asarray(labels).astype(int), np.clip(np.asarray(probs, dtype=float), 0.0, 1.0)
    out = {"brier": float(brier_score_loss(labels, probs)) if labels.size else float("nan"),
           "ece": expected_calibration_error(labels, probs) if labels.size else float("nan"),
           "log_loss": float("nan")}
    if both_classes(labels):
        out["log_loss"] = float(log_loss(labels, np.clip(probs, PROB_CLIP, 1 - PROB_CLIP)))
    return out


def full_metrics(labels, probs, threshold: float) -> dict:
    out = ranking_metrics(labels, probs)
    out.update(probability_metrics(labels, probs))
    out.update(confusion(labels, probs, threshold))
    return out


def summarize(values) -> dict:
    """Mean, median, sample std, min, max and count over finite values."""
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return {k: float("nan") if k != "n" else 0 for k in SUMMARY_STATS}
    return {"mean": float(arr.mean()), "median": float(np.median(arr)),
            "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "min": float(arr.min()), "max": float(arr.max()), "n": int(arr.size)}


def precision_at_prevalence(recall: float, false_positive_rate: float, pi: float) -> float:
    """Precision the same operating point would have if positives made up pi of the ground."""
    denom = recall * pi + false_positive_rate * (1 - pi)
    return recall * pi / denom if denom > 0 else float("nan")


# --- thresholds chosen on validation scores only -----------------------------------------------

def select_thresholds(labels, scores, precision_targets=PRECISION_TARGETS,
                      recall_targets=RECALL_TARGETS) -> dict[str, dict]:
    """Operating points picked on validation labels and scores.

    Returns {policy: {"threshold", "val_precision", "val_recall", "reachable"}}. Policies are
    `max_f1`, `precision_<p>` (lowest threshold with validation precision >= p, which keeps the
    most recall) and `recall_<r>` (highest threshold with validation recall >= r, which keeps the
    most precision). Unreachable targets keep threshold NaN and are never evaluated.
    """
    labels, scores = np.asarray(labels).astype(int), np.asarray(scores, dtype=float)
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    # precision_recall_curve returns one more precision/recall than thresholds (the empty set).
    precision, recall = precision[:-1], recall[:-1]
    out: dict[str, dict] = {}
    f1 = np.where(precision + recall > 0, 2 * precision * recall / np.maximum(precision + recall, 1e-12), 0.0)
    best = int(np.argmax(f1))
    out["max_f1"] = {"threshold": float(thresholds[best]), "val_precision": float(precision[best]),
                     "val_recall": float(recall[best]), "reachable": True}
    for target in precision_targets:
        ok = np.flatnonzero(precision >= target)
        key = f"precision_{target:.2f}"
        if ok.size:
            i = int(ok[np.argmax(recall[ok])])
            out[key] = {"threshold": float(thresholds[i]), "val_precision": float(precision[i]),
                        "val_recall": float(recall[i]), "reachable": True}
        else:
            out[key] = {"threshold": float("nan"), "val_precision": float("nan"),
                        "val_recall": float("nan"), "reachable": False}
    for target in recall_targets:
        ok = np.flatnonzero(recall >= target)
        key = f"recall_{target:.2f}"
        if ok.size:
            i = int(ok[np.argmax(thresholds[ok])])
            out[key] = {"threshold": float(thresholds[i]), "val_precision": float(precision[i]),
                        "val_recall": float(recall[i]), "reachable": True}
        else:
            out[key] = {"threshold": float("nan"), "val_precision": float("nan"),
                        "val_recall": float("nan"), "reachable": False}
    return out


def apply_thresholds(labels, scores, chosen: dict[str, dict]) -> list[dict]:
    """Evaluate thresholds picked elsewhere on held-out labels. Nothing is refit here."""
    rows = []
    for policy, pick in chosen.items():
        row = {"policy": policy, "reachable_on_validation": pick["reachable"],
               "val_precision": pick["val_precision"], "val_recall": pick["val_recall"]}
        if pick["reachable"]:
            row.update(confusion(labels, scores, pick["threshold"]))
        else:
            row["threshold"] = float("nan")
        rows.append(row)
    return rows


# --- calibrators fit on validation scores only -------------------------------------------------

def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), PROB_CLIP, 1 - PROB_CLIP)
    return np.log(p / (1 - p))


class Calibrator:
    """Raw, Platt (logistic on the score's logit) or isotonic map, fit on validation scores."""

    METHODS = ("raw", "platt", "isotonic")

    def __init__(self, method: str):
        if method not in self.METHODS:
            raise ValueError(f"unknown calibration method {method!r}")
        self.method = method
        self.model = None
        self.fitted_on = 0

    def fit(self, scores, labels) -> Calibrator:
        scores, labels = np.asarray(scores, dtype=float), np.asarray(labels).astype(int)
        self.fitted_on = int(scores.size)
        if self.method == "platt":
            self.model = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(scores)[:, None], labels)
        elif self.method == "isotonic":
            self.model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(scores, labels)
        return self

    def predict(self, scores) -> np.ndarray:
        scores = np.asarray(scores, dtype=float)
        if self.method == "raw":
            return np.clip(scores, 0.0, 1.0)
        if self.model is None:
            raise RuntimeError("calibrator used before fit")
        if self.method == "platt":
            return self.model.predict_proba(_logit(scores)[:, None])[:, 1]
        return self.model.predict(scores)


# --- distribution shift ------------------------------------------------------------------------

def standardized_mean_difference(reference, target) -> float:
    reference, target = np.asarray(reference, dtype=float), np.asarray(target, dtype=float)
    pooled = math.sqrt((reference.var(ddof=1) + target.var(ddof=1)) / 2)
    return float((target.mean() - reference.mean()) / pooled) if pooled > 0 else 0.0


def population_stability_index(reference, target, bins: int = PSI_BINS, categorical: bool = False,
                               eps: float = 1e-4) -> float:
    """PSI with reference-quantile bins (or categories). Rule of thumb: <0.1 small, >0.25 large."""
    reference, target = np.asarray(reference, dtype=float), np.asarray(target, dtype=float)
    if categorical:
        cats = np.union1d(np.unique(reference), np.unique(target))
        ref = np.array([(reference == c).mean() for c in cats])
        tgt = np.array([(target == c).mean() for c in cats])
    else:
        edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
        if edges.size < 2:
            return 0.0
        inner = edges[1:-1]
        ref = np.bincount(np.searchsorted(inner, reference, side="right"), minlength=inner.size + 1) / reference.size
        tgt = np.bincount(np.searchsorted(inner, target, side="right"), minlength=inner.size + 1) / target.size
    ref, tgt = np.maximum(ref, eps), np.maximum(tgt, eps)
    return float(np.sum((tgt - ref) * np.log(tgt / ref)))


def shift_statistics(reference, target, categorical: bool = False) -> dict:
    """SMD, PSI, KS and std-scaled Wasserstein of target against reference.

    For a categorical feature SMD, KS and Wasserstein are undefined; total variation distance
    between the category shares is reported instead.
    """
    reference, target = np.asarray(reference, dtype=float), np.asarray(target, dtype=float)
    out = {"psi": population_stability_index(reference, target, categorical=categorical)}
    if categorical:
        cats = np.union1d(np.unique(reference), np.unique(target))
        tv = 0.5 * sum(abs((reference == c).mean() - (target == c).mean()) for c in cats)
        out.update({"smd": float("nan"), "ks": float("nan"), "ks_pvalue": float("nan"),
                    "wasserstein_std": float("nan"), "total_variation": float(tv)})
        return out
    ks = stats.ks_2samp(reference, target)
    scale = reference.std(ddof=1)
    out.update({
        "smd": standardized_mean_difference(reference, target),
        "ks": float(ks.statistic), "ks_pvalue": float(ks.pvalue),
        "wasserstein_std": float(stats.wasserstein_distance(reference, target) / scale) if scale > 0 else 0.0,
        "total_variation": float("nan"),
    })
    return out
