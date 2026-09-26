#!/usr/bin/env python3
"""Export the selected geographic-validation LightGBM booster.

The exported ``.model`` file is LightGBM's native text model format.  The extension is
only a naming convention; LightGBM does not require a special filename suffix.

Run from the repository root:

  python ml/scripts/export_geo_model.py

The exporter deliberately retrains on the six in-domain regions only.  Rainier rows are
kept completely outside the fit and are never used to select parameters, calibrators, or
thresholds.  The model is a regional terrain-susceptibility model, not the 72-hour
event-time rainfall classifier.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import geo_validate as gv  # noqa: E402
from build_regional_features import TABLE_PATH  # noqa: E402


DEFAULT_OUT = REPO_ROOT / "ml" / "artifacts" / "geo_validation"
DEFAULT_REPORT = DEFAULT_OUT / "report.json"


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _calibrator_metadata(fitted: gv.Fitted) -> dict:
    """Serialize validation-only calibration maps for later integration."""
    out = {
        "fit_source": "inner_leave_one_region_out_oof",
        "validation_rows": int(len(fitted.validation_labels)),
        "validation_positives": int(fitted.validation_labels.sum()),
        "methods": {"raw": {}}
    }
    platt = fitted.calibrators["platt"].model
    out["methods"]["platt"] = {
        "kind": "logit_logistic",
        "coef": float(platt.coef_[0, 0]),
        "intercept": float(platt.intercept_[0]),
    }
    isotonic = fitted.calibrators["isotonic"].model
    out["methods"]["isotonic"] = {
        "kind": "piecewise_linear",
        "x_thresholds": [float(v) for v in isotonic.X_thresholds_],
        "y_thresholds": [float(v) for v in isotonic.y_thresholds_],
    }
    return out


def export_model(table_path: Path, report_path: Path, out_dir: Path, family_name: str = "selected") -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    selected = report["selection"]["family"] if family_name == "selected" else family_name
    try:
        family = gv.FAMILY_BY_NAME[selected]
    except KeyError as exc:
        raise ValueError(f"unknown model family {selected!r}") from exc
    if family.kind != "lgbm":
        raise ValueError(f"{selected!r} is not a LightGBM family")

    table = gv.with_regions(pd.read_parquet(table_path))
    train = table[table["set"] == "train"].copy()
    if train.empty or train["label"].nunique() != 2:
        raise ValueError("training table must contain both classes in the in-domain rows")
    if (table["set"] == "external").sum() == 0:
        raise ValueError("expected external Rainier rows so the exporter can verify holdout separation")

    print(f"fitting {selected} on {len(train)} in-domain rows")
    fitted = gv.fit_with_validation(train, family)
    model = fitted.scorer.model
    if model is None or not hasattr(model, "booster_"):
        raise RuntimeError("selected scorer did not produce a LightGBM booster")

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"{selected}.model"
    partial = model_path.with_name(model_path.name + ".part")
    model.booster_.save_model(str(partial))
    partial.replace(model_path)

    region_counts = (
        train.groupby("region", sort=True)["label"]
        .agg(rows="size", positives="sum")
        .reset_index()
        .to_dict(orient="records")
    )
    metadata = {
        "format": "lightgbm_native_text",
        "file_extension_note": ".model is a filename convention; load with lightgbm.Booster(model_file=...)",
        "model_path": _relative(model_path),
        "model_family": selected,
        "model_purpose": "regional terrain susceptibility",
        "not_event_time_classifier": True,
        "features": list(family.features),
        "categorical_features": [gv.CATEGORICAL] if gv.CATEGORICAL in family.features else [],
        "params": _jsonable(fitted.params),
        "training_table": _relative(table_path),
        "training_set_filter": "set == 'train'",
        "external_holdout_filter": "set == 'external'",
        "training_rows": int(len(train)),
        "training_positives": int(train["label"].sum()),
        "training_prevalence": float(train["label"].mean()),
        "regions": region_counts,
        "rainier_rows_excluded_from_fit": int((table["set"] == "external").sum()),
        "selection": _jsonable(report["selection"]),
        "validation": _jsonable(fitted.selection),
        "calibration": _calibrator_metadata(fitted),
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": int(gv.RANDOM_SEED),
    }
    metadata_path = out_dir / f"{selected}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    calibration_path = out_dir / f"{selected}.calibration.json"
    calibration_path.write_text(json.dumps(metadata["calibration"], indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_relative(model_path)}")
    print(f"wrote {_relative(metadata_path)}")
    print(f"wrote {_relative(calibration_path)}")
    return metadata


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=TABLE_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--family", default="selected", help="family name or 'selected' from report.json")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    export_model(args.table, args.report, args.out, args.family)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
