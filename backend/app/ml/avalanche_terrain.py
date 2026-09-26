"""A knowledge-driven avalanche terrain index, used until the trained raster is built (step 34).

This is the avalanche twin of `ml/artifacts/susceptibility.tif`. The ML track will replace it
with a LightGBM model baked to `ml/artifacts/avalanche_susceptibility.tif` from
`avalanche_lgbm.txt`, exactly as the landslide path does; `app/ml/avalanche.py` prefers that
file the moment it exists and only falls back here.

NOTHING HERE IS TRAINED. There are no avalanche labels in this repo, so there is no model to
fit and no AUC to publish. What this computes is the textbook start-zone recipe applied to the
same 30 m feature stack the landslide model reads (`data/processed/features.tif`):

- Slope is the precondition. Avalanches release overwhelmingly on 30-45 degrees; below about
  25 the snow does not slide, and above about 55 it sluffs continuously instead of building a
  slab. Modeled as a band peaking at 38 degrees, not as "steeper is worse".
- Trees anchor snow. Closed forest rarely produces a start zone; open, bare, and glacier
  ground does. Taken from the WorldCover class.
- Start zones sit high, near and above treeline, so elevation raises the index over a soft
  ramp rather than a hard cut.
- Convex ground is where slabs fracture, so positive curvature adds a little.

Every term is a named constant with the reason beside it, and `metrics()` reports
`trained: false` with `auc: null`, which is the same rule the landslide packs follow: never
present a knowledge-driven index as a trained model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from app.config import REPO_ROOT

FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.tif"
FEATURE_BANDS = ("elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi")

METHOD = "knowledge-driven avalanche terrain index (not trained)"

# --- Slope: the start-zone band -------------------------------------------------------------
# McClung and Schaerer, The Avalanche Handbook: most slab avalanches release between 30 and 45
# degrees, with the mode close to 38. A Gaussian band centered there scores the release angle
# rather than raw steepness, which is why this is not the landslide model with a new name.
SLOPE_PEAK_DEG = 38.0
SLOPE_WIDTH_DEG = 9.0    # about half the 30-45 band per standard deviation
SLOPE_FLOOR_DEG = 22.0   # below this snow essentially does not release: the index goes to zero
SLOPE_CEILING_DEG = 60.0 # above this the slope sluffs continuously and cannot hold a slab

# --- Ground cover: what anchors the snow ----------------------------------------------------
# ESA WorldCover classes. Closed canopy holds the snowpack in place; bare rock, grass, moss and
# permanent snow or ice are open start-zone ground.
TREE_COVER = 10
SHRUBLAND = 20
GRASSLAND = 30
BARE = 60
SNOW_AND_ICE = 70
MOSS = 100
WATER = 80
# Multipliers on the terrain index, by how much the cover anchors snow.
COVER_FACTOR: dict[int, float] = {
    TREE_COVER: 0.25,    # closed forest: start zones are rare
    SHRUBLAND: 0.70,     # buried brush is a poor anchor once covered
    GRASSLAND: 1.00,     # smooth ground: a good bed surface
    BARE: 1.00,
    MOSS: 1.00,
    SNOW_AND_ICE: 1.10,  # permanent snowfields feed the biggest paths
}
DEFAULT_COVER_FACTOR = 0.85  # cropland, wetland and the rest: no strong reason either way

# --- Elevation: start zones sit high --------------------------------------------------------
# A soft ramp, not a treeline cut: the real treeline moves with aspect and year, and a hard
# edge would paint a false line across the map.
ELEVATION_LOW_M = 1200.0   # below this, a start zone is unusual on this massif
ELEVATION_HIGH_M = 2000.0  # above this, elevation stops adding
ELEVATION_MIN_FACTOR = 0.45

# --- Curvature: where a slab breaks ---------------------------------------------------------
# Convex rollovers concentrate tension and are where crowns tend to appear. Small effect: it
# nudges the index, it does not drive it.
CURVATURE_GAIN = 0.10
CURVATURE_CLIP = 1.0


@dataclass(frozen=True)
class TerrainIndex:
    """The index on the feature stack's own grid."""

    values: np.ndarray  # float32 0-1, NaN off the grid and on water
    transform: Affine
    crs: str


def _band_ramp(values: np.ndarray, peak: float, width: float, floor: float, ceiling: float) -> np.ndarray:
    """A 0-1 Gaussian band around `peak`, cut to zero outside [floor, ceiling]."""
    with np.errstate(invalid="ignore"):
        band = np.exp(-0.5 * ((values - peak) / width) ** 2)
        band = np.where((values < floor) | (values > ceiling), 0.0, band)
    return band


def _cover_factor(landcover: np.ndarray) -> np.ndarray:
    """The anchoring multiplier per cell, from the WorldCover class."""
    factor = np.full(landcover.shape, DEFAULT_COVER_FACTOR, dtype="float32")
    codes = landcover.astype("int32", copy=False)
    for code, value in COVER_FACTOR.items():
        factor[codes == code] = value
    return factor


def _elevation_factor(elevation: np.ndarray) -> np.ndarray:
    """A soft ramp from ELEVATION_MIN_FACTOR at low ground to 1.0 near and above treeline."""
    with np.errstate(invalid="ignore"):
        ramp = (elevation - ELEVATION_LOW_M) / (ELEVATION_HIGH_M - ELEVATION_LOW_M)
    return (ELEVATION_MIN_FACTOR + (1.0 - ELEVATION_MIN_FACTOR) * np.clip(ramp, 0.0, 1.0)).astype("float32")


@lru_cache(maxsize=4)
def _read_stack(path: Path, mtime_ns: int) -> tuple[dict[str, np.ndarray], Affine, str]:
    with rasterio.open(path) as src:
        if tuple(src.descriptions) != FEATURE_BANDS:
            raise ValueError(f"{path} bands {src.descriptions} are not {FEATURE_BANDS}")
        data = src.read(masked=True).astype("float32").filled(np.nan)
        crs = src.crs.to_string() if src.crs else ""
        return dict(zip(FEATURE_BANDS, data, strict=True)), src.transform, crs


def compute(path: Path = FEATURES_PATH) -> TerrainIndex:
    """Score the avalanche terrain index over the feature stack.

    Cells outside the data, and cells on water, stay NaN so the tiler and the hazard sampler
    never turn them into risk. That matches what the landslide path does.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"{_display(path)} is missing (the 30 m feature stack the avalanche terrain index "
            "reads). From repo root: python ml/scripts/download_sources.py --only dem,landcover "
            "&& python ml/scripts/build_features.py"
        )
    band, transform, crs = _read_stack(path, path.stat().st_mtime_ns)

    slope = _band_ramp(band["slope"], SLOPE_PEAK_DEG, SLOPE_WIDTH_DEG, SLOPE_FLOOR_DEG, SLOPE_CEILING_DEG)
    cover = _cover_factor(np.nan_to_num(band["landcover"], nan=-1.0))
    elevation = _elevation_factor(band["elevation"])
    with np.errstate(invalid="ignore"):
        curvature = 1.0 + CURVATURE_GAIN * np.clip(band["curvature"], -CURVATURE_CLIP, CURVATURE_CLIP)

    index = (slope * cover * elevation * curvature).astype("float32")

    valid = np.isfinite(band["slope"]) & np.isfinite(band["elevation"]) & np.isfinite(band["landcover"])
    valid &= band["landcover"] != WATER  # snow does not sit on open water
    values = np.full(index.shape, np.nan, dtype="float32")
    values[valid] = np.clip(index[valid], 0.0, 1.0)
    return TerrainIndex(values=values, transform=transform, crs=crs)


def contributions(slope_deg: float, landcover: int, elevation_m: float, curvature: float) -> dict[str, float]:
    """Each term at one cell, so an agent can be shown why a place scored what it did."""
    slope = float(_band_ramp(np.array([slope_deg], dtype="float32"),
                             SLOPE_PEAK_DEG, SLOPE_WIDTH_DEG, SLOPE_FLOOR_DEG, SLOPE_CEILING_DEG)[0])
    cover = float(_cover_factor(np.array([landcover], dtype="float32"))[0])
    elevation = float(_elevation_factor(np.array([elevation_m], dtype="float32"))[0])
    bend = float(1.0 + CURVATURE_GAIN * np.clip(curvature, -CURVATURE_CLIP, CURVATURE_CLIP))
    return {
        "slope_band": round(slope, 3),
        "cover_factor": round(cover, 3),
        "elevation_factor": round(elevation, 3),
        "curvature_factor": round(bend, 3),
        "index": round(min(max(slope * cover * elevation * bend, 0.0), 1.0), 3),
        "slope_peak_deg": SLOPE_PEAK_DEG,
    }


def metrics() -> dict:
    """The model card for this index. It is not trained, and it says so."""
    return {
        "method": METHOD,
        "trained": False,
        "auc": None,
        "weights": {
            "slope_peak_deg": SLOPE_PEAK_DEG,
            "slope_width_deg": SLOPE_WIDTH_DEG,
            "slope_band_deg": [SLOPE_FLOOR_DEG, SLOPE_CEILING_DEG],
            "cover_factor": {str(k): v for k, v in COVER_FACTOR.items()},
            "elevation_ramp_m": [ELEVATION_LOW_M, ELEVATION_HIGH_M],
            "curvature_gain": CURVATURE_GAIN,
        },
        "note": (
            "Knowledge-driven start-zone index from published avalanche terrain rules "
            "(slope band, canopy anchoring, elevation, convexity). No avalanche labels exist "
            "in this repo, so nothing is fitted and no skill is measured. It ranks terrain; "
            "it is not a probability. Replaced by avalanche_susceptibility.tif when the ML "
            "track bakes one."
        ),
    }


def _display(path: Path) -> Path | str:
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path
