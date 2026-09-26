"""Local ML artifact checks for /health and clearer run failures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT
from app.ml.probability import SUSCEPTIBILITY_PATH
from app.ml.tiles import TILES_DIR, read_metadata

FEATURES_STACK = REPO_ROOT / "data" / "processed" / "features.tif"

SETUP_STEPS = (
    "python ml/scripts/download_sources.py --only dem,landcover",
    "python ml/scripts/build_features.py",
    "python ml/scripts/train_susceptibility.py",
    "python ml/scripts/render_tiles.py",
)


@dataclass(frozen=True)
class SetupCheck:
    """One prerequisite for scoring and map layers."""

    id: str
    ok: bool
    path: str
    hint: str


def setup_checks() -> list[SetupCheck]:
    """What is missing on disk for Rainier layers and Analyze."""
    checks = [
        SetupCheck(
            id="features_stack",
            ok=FEATURES_STACK.is_file(),
            path=str(FEATURES_STACK.relative_to(REPO_ROOT)),
            hint=SETUP_STEPS[0] + " then " + SETUP_STEPS[1],
        ),
        SetupCheck(
            id="susceptibility_tif",
            ok=SUSCEPTIBILITY_PATH.is_file(),
            path=str(SUSCEPTIBILITY_PATH.relative_to(REPO_ROOT)),
            hint=SETUP_STEPS[2],
        ),
        SetupCheck(
            id="tiles_susceptibility",
            ok=read_metadata("susceptibility") is not None,
            path=str((TILES_DIR / "susceptibility").relative_to(REPO_ROOT)),
            hint=SETUP_STEPS[3],
        ),
        SetupCheck(
            id="tiles_probability",
            ok=read_metadata("probability") is not None,
            path=str((TILES_DIR / "probability").relative_to(REPO_ROOT)),
            hint="Run Analyze now after susceptibility exists, or: cd backend && python -m app.assessment --save",
        ),
    ]
    return checks


def setup_ready_for_analyze() -> bool:
    """True when scoring can run (susceptibility GeoTIFF present)."""
    return SUSCEPTIBILITY_PATH.is_file()


def setup_summary() -> dict:
    """JSON-safe status for GET /health."""
    checks = setup_checks()
    missing = [c for c in checks if not c.ok]
    return {
        "analyze_ready": setup_ready_for_analyze(),
        "checks": [
            {"id": c.id, "ok": c.ok, "path": c.path, "hint": c.hint if not c.ok else None}
            for c in checks
        ],
        "missing_count": len(missing),
        "next_step": missing[0].hint if missing else None,
    }


def format_missing_artifacts(exc: BaseException) -> str:
    """Turn a scoring failure into a short message with the next fix."""
    summary = setup_summary()
    next_step = summary.get("next_step")
    base = str(exc).strip()
    if next_step:
        return f"{base} Next: from repo root, {next_step}"
    return base
