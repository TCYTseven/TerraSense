"""The 72-hour avalanche probability map (step 34): the avalanche twin of app/ml/probability.py.

Same shape as the landslide path, deliberately, so everything downstream is shared. This module
hands back the same `ProbabilityMap` on the same 30 m grid, which means the tiler, the hazard
zone, the segment scoring, the bypass, and the trail scan all work for avalanches without
knowing that they do.

The three-layer story matches Model B's:

    terrain (where snow can release)  x  trigger (what the weather is doing to it)

- Terrain comes from `ml/artifacts/avalanche_susceptibility.tif` when the ML track has baked
  one from `avalanche_lgbm.txt`, exactly as the landslide path reads susceptibility.tif. Until
  then it is the knowledge-driven start-zone index in app/ml/avalanche_terrain.py, and the
  method string says so everywhere it travels.
- The trigger is `snow_signals` below: new snow load, wind slab, warming, and rain-on-snow,
  each a bounded signal against a published reference threshold.
- When a rebuilt trigger module `app/ml/avalanche_model.py` appears, score() calls its
  `run(weather)` and reads `.probability`, `.transform`, and `.crs`, which is the same seam
  contract app/ml/probability.py pins for Model B. Adapt `_from_model()` and nothing else.

NOT TRAINED. No avalanche labels exist in this repo. Both the terrain index and the trigger
weights are knowledge-driven, `validation()` returns None, and the model card says
`trained: false`. Nothing here may be presented as a fitted model or as a calibrated
probability: it ranks places and days.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path

import numpy as np
import rasterio

from app.config import REPO_ROOT
from app.ml import avalanche_terrain
from app.ml.probability import ProbabilityMap
from app.weather import HourlyRain

logger = logging.getLogger(__name__)

SUSCEPTIBILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "avalanche_susceptibility.tif"
PROBABILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "avalanche_probability.tif"
METRICS_PATH = REPO_ROOT / "ml" / "artifacts" / "avalanche_metrics.json"

TRAINED_METHOD = "avalanche model (LightGBM terrain x snow trigger)"
BAKED_METHOD = "avalanche terrain raster x snow trigger (not trained)"
STAND_IN_METHOD = "avalanche stand-in: knowledge-driven terrain x snow trigger (not trained)"

# --- The snow trigger -----------------------------------------------------------------------
#
# A logistic layer over four bounded signals, the same arithmetic Model B uses for rain. The
# weights are NOT fitted: they are ordered by how strongly each factor features in avalanche
# forecasting practice, and each carries its reason. They rank days; they are not calibrated.

# New snow is the dominant loading term. About 30 cm in 24 h is the classic storm-slab
# benchmark, so 50 cm over 72 h is the reference total this scores against.
NEW_SNOW_REFERENCE_CM = 50.0
W_NEW_SNOW = 1.60

# Wind moves far more snow than it drops. Sustained transport starts around 25 km/h and slabs
# build fast above 50, which is the reference here.
WIND_REFERENCE_KMH = 50.0
WIND_ONSET_KMH = 25.0
W_WIND_SLAB = 1.10

# A rising freezing level and above-freezing air weaken bonds and drive wet-snow release.
WARMING_REFERENCE_C = 4.0
W_WARMING = 0.85

# Rain on snow both loads the pack and lubricates it: the sharpest short-term destabilizer
# there is, but only when there is snow to rain on.
RAIN_ON_SNOW_REFERENCE_MM = 25.0
W_RAIN_ON_SNOW = 1.25

# The quiet-day baseline. Negative, so a calm day on steep ground is not "high".
W_BASELINE = -1.45
# Terrain enters as log-odds of the index, like Model B's terrain term.
W_TERRAIN = 1.0
TERRAIN_BASE_LOGIT = float(np.log(0.25 / 0.75))
TERRAIN_CLIP = 1e-3

SNOW_WINDOW_HOURS = 72
WIND_WINDOW_HOURS = 24


def _bounded(total: float, reference: float, onset: float = 0.0) -> float:
    """A stable -1..1 signal: -1 well under the reference, 0 at it, +1 well over."""
    if reference <= onset:
        return 0.0
    return float(np.clip((total - onset) / (reference - onset) - 1.0, -1.0, 1.0))


def snow_signals(weather: HourlyRain | None) -> dict[str, float]:
    """The four trigger signals and the totals behind them.

    Missing weather is an explicit quiet fallback, never a silent refetch and never a pretend
    observation: the run still scores terrain, and every signal sits at its calm end.
    """
    if weather is None:
        return {
            "new_snow_cm": 0.0, "wind_max_kmh": 0.0, "temp_max_c": 0.0, "rain_mm": 0.0,
            "snow_on_ground": False,
            "new_snow_load": -1.0, "wind_slab": -1.0, "warming": -1.0, "rain_on_snow": -1.0,
        }

    snowfall = weather.window(weather.snowfall_cm, 0, SNOW_WINDOW_HOURS) if weather.snowfall_cm else []
    winds = weather.window(weather.wind_kmh, 0, WIND_WINDOW_HOURS) if weather.wind_kmh else []
    temps = weather.window(weather.temperature_c, 0, SNOW_WINDOW_HOURS) if weather.temperature_c else []

    new_snow_cm = float(sum(snowfall))
    wind_max = float(max(winds)) if winds else 0.0
    temp_max = float(max(temps)) if temps else 0.0
    rain_mm = weather.total(0, SNOW_WINDOW_HOURS)

    # Rain only destabilizes a pack that exists. Fresh snow in the window, or air cold enough
    # to have held snow, is the evidence we have; without either, rain-on-snow stays at its
    # calm end rather than inventing a snowpack.
    temps_min = float(min(temps)) if temps else 0.0
    snow_on_ground = new_snow_cm > 0.0 or temps_min <= 0.0

    return {
        "new_snow_cm": round(new_snow_cm, 1),
        "wind_max_kmh": round(wind_max, 1),
        "temp_max_c": round(temp_max, 1),
        "rain_mm": round(rain_mm, 1),
        "snow_on_ground": snow_on_ground,
        "new_snow_load": _bounded(new_snow_cm, NEW_SNOW_REFERENCE_CM),
        "wind_slab": _bounded(wind_max, WIND_REFERENCE_KMH, WIND_ONSET_KMH),
        "warming": _bounded(temp_max, WARMING_REFERENCE_C),
        "rain_on_snow": _bounded(rain_mm, RAIN_ON_SNOW_REFERENCE_MM) if snow_on_ground else -1.0,
    }


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, TERRAIN_CLIP, 1.0 - TERRAIN_CLIP)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        return 1.0 / (1.0 + np.exp(-np.clip(values, -60.0, 60.0)))


def contributions(terrain_index: float, weather: HourlyRain | None) -> dict[str, float]:
    """Each input's term in the logit at one cell, plus the totals behind them."""
    signals = snow_signals(weather)
    return {
        "terrain": float(W_TERRAIN * (_logit(np.float64(terrain_index)) - TERRAIN_BASE_LOGIT)),
        "baseline": W_BASELINE,
        "new_snow_load": W_NEW_SNOW * signals["new_snow_load"],
        "wind_slab": W_WIND_SLAB * signals["wind_slab"],
        "warming": W_WARMING * signals["warming"],
        "rain_on_snow": W_RAIN_ON_SNOW * signals["rain_on_snow"],
        "new_snow_cm": signals["new_snow_cm"],
        "wind_max_kmh": signals["wind_max_kmh"],
        "temp_max_c": signals["temp_max_c"],
        "rain_mm": signals["rain_mm"],
        "reference_new_snow_cm": NEW_SNOW_REFERENCE_CM,
        "reference_wind_kmh": WIND_REFERENCE_KMH,
    }


def _trigger_module():
    """app.ml.avalanche_model if the ML track has shipped it, else None."""
    try:
        return importlib.import_module("app.ml.avalanche_model")
    except ModuleNotFoundError as exc:
        if exc.name != "app.ml.avalanche_model":
            raise
        return None


def _from_model(module, weather: HourlyRain | None, susceptibility: Path | None) -> ProbabilityMap:
    """The pinned seam, matching app/ml/probability.py: run(weather) or run(weather, path=...)."""
    if susceptibility is None or susceptibility == SUSCEPTIBILITY_PATH:
        result = module.run(weather)
    else:
        result = module.run(weather, path=susceptibility)
    values = np.asarray(result.probability, dtype="float32")
    return ProbabilityMap(values, result.transform, str(result.crs), TRAINED_METHOD)


def _terrain(susceptibility: Path | None) -> tuple[np.ndarray, object, str, str]:
    """The terrain layer: the baked raster when it exists, else the knowledge-driven index."""
    path = susceptibility or SUSCEPTIBILITY_PATH
    if path.is_file():
        with rasterio.open(path) as src:
            masked = src.read(1, masked=True).astype("float32")
            values = np.asarray(masked.filled(np.nan), dtype="float32")
            crs = src.crs.to_string() if src.crs else ""
            return values, src.transform, crs, BAKED_METHOD
    logger.info(
        "%s is not built: the avalanche map uses the knowledge-driven terrain index",
        path.name,
    )
    index = avalanche_terrain.compute()
    return index.values, index.transform, index.crs, STAND_IN_METHOD


def score(weather: HourlyRain | None = None, susceptibility: Path | None = None) -> ProbabilityMap:
    """The current 72-hour avalanche map: the trained model when it exists, else terrain x trigger.

    `susceptibility` points at one pack's avalanche raster; None keeps Rainier's.
    """
    module = _trigger_module()
    if module is not None:
        return _from_model(module, weather, susceptibility)

    terrain, transform, crs, method = _terrain(susceptibility)
    signals = snow_signals(weather)
    valid = np.isfinite(terrain)
    with np.errstate(invalid="ignore"):
        terrain_term = _logit(terrain) - TERRAIN_BASE_LOGIT
    logit = (
        W_TERRAIN * terrain_term
        + W_BASELINE
        + W_NEW_SNOW * signals["new_snow_load"]
        + W_WIND_SLAB * signals["wind_slab"]
        + W_WARMING * signals["warming"]
        + W_RAIN_ON_SNOW * signals["rain_on_snow"]
    )
    values = np.full(terrain.shape, np.nan, dtype="float32")
    values[valid] = _sigmoid(logit[valid]).astype("float32")
    return ProbabilityMap(values, transform, crs, method)


def is_trained() -> bool:
    """True only once a fitted avalanche model is actually in the tree."""
    return _trigger_module() is not None


def validation() -> dict | None:
    """Held-out skill for the avalanche map. None until something here is actually fitted.

    Mirrors app/ml/probability.validation(). It returns None rather than an empty shell so a
    caller cannot mistake "not measured" for "measured at zero".
    """
    if not METRICS_PATH.is_file():
        return None
    try:
        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return metrics.get("validation") or None


def model_card() -> dict:
    """What made this map, for the agents' get_model_prediction and the advisory."""
    if METRICS_PATH.is_file():
        try:
            return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"note": f"avalanche_metrics.json could not be read ({type(exc).__name__})."}
    card = avalanche_terrain.metrics()
    card["trigger"] = {
        "method": "knowledge-driven snow trigger (not fitted)",
        "weights": {
            "baseline": W_BASELINE,
            "new_snow_load": W_NEW_SNOW,
            "wind_slab": W_WIND_SLAB,
            "warming": W_WARMING,
            "rain_on_snow": W_RAIN_ON_SNOW,
        },
        "references": {
            "new_snow_cm_72h": NEW_SNOW_REFERENCE_CM,
            "wind_kmh_24h": WIND_REFERENCE_KMH,
            "wind_onset_kmh": WIND_ONSET_KMH,
            "warming_c": WARMING_REFERENCE_C,
            "rain_on_snow_mm": RAIN_ON_SNOW_REFERENCE_MM,
        },
        "note": (
            "Ordered by forecasting practice, not fitted to data. Ranks days; not calibrated."
        ),
    }
    return card


# --- Naming the release ---------------------------------------------------------------------
#
# The landslide zone finder names its hazard from the ground under the zone. An avalanche on
# the same ground is named from what the weather is doing to the snow on it, which is the
# distinction a forecaster actually makes.

# Warming or rain on the pack points at a wet release rather than a dry slab.
WET_WARMING_C = 1.0
WET_RAIN_MM = 5.0
# Wind or new snow builds a cohesive slab; without either, what moves is loose snow.
SLAB_NEW_SNOW_CM = 10.0
SLAB_WIND_KMH = WIND_ONSET_KMH


def type_hint(signals: dict[str, float]) -> str:
    """The avalanche type these snow signals point at. The Snowpack Analyst may move it."""
    if not signals.get("snow_on_ground", False):
        # No pack to release. Still a start zone, so name the default and let the agent and
        # the level carry how unlikely it is.
        return "slab_avalanche"
    if signals.get("temp_max_c", 0.0) >= WET_WARMING_C and signals.get("rain_mm", 0.0) >= WET_RAIN_MM:
        return "wet_snow_avalanche"
    if signals.get("new_snow_cm", 0.0) >= SLAB_NEW_SNOW_CM or signals.get("wind_max_kmh", 0.0) >= SLAB_WIND_KMH:
        return "slab_avalanche"
    return "loose_snow_avalanche"


def drivers_hint(signals: dict[str, float], terrain: dict | None) -> tuple[str, ...]:
    """The avalanche drivers these facts support, worst first. The analyst picks from them."""
    found: list[str] = []
    if signals.get("new_snow_cm", 0.0) >= SLAB_NEW_SNOW_CM:
        found.append("new_snow_load")
    if signals.get("wind_max_kmh", 0.0) >= WIND_ONSET_KMH:
        found.append("wind_slab")
    if signals.get("rain_on_snow", -1.0) > -1.0 and signals.get("rain_mm", 0.0) >= WET_RAIN_MM:
        found.append("rain_on_snow")
    if signals.get("temp_max_c", 0.0) >= WARMING_REFERENCE_C:
        found.append("warming_instability")
    if terrain:
        slope = (terrain.get("slope_deg") or {}).get("mean")
        if slope is not None and avalanche_terrain.SLOPE_FLOOR_DEG <= slope <= avalanche_terrain.SLOPE_CEILING_DEG:
            found.append("slope_angle")
        if terrain.get("share_sparse_cover", 0.0) >= 0.5:
            found.append("open_slope")
        if (terrain.get("curvature_mean") or 0.0) >= 0.2:
            found.append("convex_rollover")
        elevation = (terrain.get("elevation_m") or {}).get("min")
        if elevation is not None and elevation >= avalanche_terrain.ELEVATION_HIGH_M:
            found.append("above_treeline")
    return tuple(dict.fromkeys(found))[:4] or ("slope_angle",)
