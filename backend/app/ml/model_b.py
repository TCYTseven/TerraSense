"""Model B: 72-hour landslide probability from susceptibility and rain (implementation step 17).

    P = sigmoid(W_SUSCEPTIBILITY * susceptibility + W_RAIN * rainfall_exceedance
                + W_MOISTURE * moisture_index + BIAS)

- susceptibility: Model A's 0-1 map on the 30 m grid (ml/artifacts/susceptibility.tif).
- rainfall_exceedance: the worst rain in the 72 hours before and after now, measured against a
  rainfall intensity-duration threshold, as log2 of the ratio. 0 at the threshold, +1 at twice it.
- moisture_index: a one-week antecedent precipitation index. 1 means a wet week.

Rain is one value for the whole box, so the map's shape comes from susceptibility and the rain
sets how high it runs. The weights are set by hand: no dated Rainier landslides are available
to fit them to (the catalog download is blocked), so each is an explicit, documented judgment.

Run from backend/:  python -m app.ml.model_b
"""

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from app.config import REPO_ROOT
from app.weather import HourlyRain, daily_totals_before_now, get_hourly_rain, window_hours

SUSCEPTIBILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"
PROBABILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "probability.tif"

# Guzzetti et al. (2008), the global minimum intensity-duration threshold for shallow
# landslides and debris flows: I = 2.20 * D^-0.44, with I in mm/h and D in hours.
ID_THRESHOLD_A = 2.20
ID_THRESHOLD_B = -0.44
DURATIONS_H = (6, 12, 24, 48, 72)  # storm lengths checked against the threshold
EXCEEDANCE_RANGE = (-2.0, 3.0)  # log2 ratio: a dry spell reads -2, eight times the threshold +3

# Antecedent precipitation index over the past week: the last 24 hours count fully and each
# earlier day 15% less. 40 mm of index is a wet week (moisture 1).
API_DECAY_PER_DAY = 0.85
API_WET_WEEK_MM = 40.0
MOISTURE_MAX = 2.0

# Model B weights, on the logit scale. Hand-set so three reference scenarios land sensibly:
#   dry week (exceedance -2, moisture 0):        susceptibility 1 -> 0.10
#   storm at the threshold after a wet week (0, 1): susceptibility 1 -> 0.60, 0.5 -> 0.11
#   4x-threshold storm after a soaked week (2, 2):  susceptibility 1 -> 0.95, 0.5 -> 0.62, 0 -> 0.12
# Guzzetti's threshold is a global lower envelope that Pacific Northwest storms often pass, so
# the rain terms stay smaller than the terrain term: even a big storm leaves the map's shape
# readable instead of turning the whole mountain red.
W_SUSCEPTIBILITY = 5.0  # terrain decides where ground can fail: the 0-1 range spans 5 logits
W_RAIN = 1.0  # each doubling of the threshold intensity adds 1
W_MOISTURE = 0.6  # a soaked week adds up to 1.2
BIAS = -5.2  # sets the dry-week ceiling above

# Shared facts: probability bins.
RISK_BINS = ((0.2, "low"), (0.45, "moderate"), (0.7, "high"))  # above 0.7 is extreme


def risk_level(probability: float) -> str:
    """The shared risk level for a probability."""
    for upper, level in RISK_BINS:
        if probability < upper:
            return level
    return "extreme"


@dataclass(frozen=True)
class RainSignal:
    """The rain terms of Model B and the totals behind them."""

    past_72h_mm: float
    past_7d_mm: float
    next_24h_mm: float
    next_72h_mm: float
    exceedance: float
    worst_duration_h: int
    threshold_ratio: float
    moisture_index: float
    source: str


@dataclass(frozen=True)
class ModelBResult:
    probability: np.ndarray  # float32 on the susceptibility grid, NaN outside the data
    transform: Affine
    crs: str
    rain: RainSignal


def rain_signal(rain: HourlyRain) -> RainSignal:
    """Rainfall exceedance and antecedent moisture from hourly precipitation."""
    window = np.asarray(window_hours(rain, 72, 72), dtype="float64")
    sums = np.concatenate([[0.0], np.cumsum(window)])
    worst_ratio, worst_duration = 0.0, DURATIONS_H[0]
    for duration in DURATIONS_H:
        if len(window) < duration:
            continue
        worst_total = float(np.max(sums[duration:] - sums[:-duration]))
        ratio = (worst_total / duration) / (ID_THRESHOLD_A * duration**ID_THRESHOLD_B)
        if ratio > worst_ratio:
            worst_ratio, worst_duration = ratio, duration
    exceedance = float(np.clip(np.log2(max(worst_ratio, 1e-6)), *EXCEEDANCE_RANGE))

    daily = daily_totals_before_now(rain, 7)
    api = sum(total * API_DECAY_PER_DAY**day for day, total in enumerate(daily))
    return RainSignal(
        past_72h_mm=round(rain.total(-72, 0), 1),
        past_7d_mm=round(rain.total(-168, 0), 1),
        next_24h_mm=round(rain.total(0, 24), 1),
        next_72h_mm=round(rain.total(0, 72), 1),
        exceedance=round(exceedance, 3),
        worst_duration_h=worst_duration,
        threshold_ratio=round(worst_ratio, 2),
        moisture_index=round(float(np.clip(api / API_WET_WEEK_MM, 0, MOISTURE_MAX)), 3),
        source=rain.source,
    )


def probability(susceptibility: np.ndarray, signal: RainSignal) -> np.ndarray:
    """Model B on every cell. NaN stays NaN."""
    logit = (W_SUSCEPTIBILITY * susceptibility + W_RAIN * signal.exceedance
             + W_MOISTURE * signal.moisture_index + BIAS)
    return (1 / (1 + np.exp(-logit))).astype("float32")


def run(rain: HourlyRain | None = None, susceptibility_path: Path = SUSCEPTIBILITY_PATH) -> ModelBResult:
    """Score the whole map from the current (or given) rain."""
    with rasterio.open(susceptibility_path) as src:
        susceptibility, transform, crs = src.read(1), src.transform, src.crs.to_string()
    signal = rain_signal(rain or get_hourly_rain())
    return ModelBResult(probability(susceptibility, signal), transform, crs, signal)


def summarize(values: np.ndarray) -> dict:
    """Cell count, range, and the share of cells in each shared risk bin."""
    valid = values[~np.isnan(values)]
    edges = [0.0, 0.2, 0.45, 0.7, 1.0001]
    shares = np.histogram(valid, bins=edges)[0] / valid.size
    return {
        "cells": int(valid.size),
        "min": round(float(valid.min()), 3),
        "mean": round(float(valid.mean()), 3),
        "max": round(float(valid.max()), 3),
        "share": dict(zip(["low", "moderate", "high", "extreme"], (round(float(s), 3) for s in shares),
                          strict=True)),
    }


def write_probability(result: ModelBResult, path: Path = PROBABILITY_PATH) -> None:
    """Save the probability map on the susceptibility grid, for tiles and the hazard polygon."""
    profile = {
        "driver": "GTiff", "width": result.probability.shape[1], "height": result.probability.shape[0],
        "count": 1, "dtype": "float32", "crs": result.crs, "transform": result.transform, "nodata": np.nan,
        "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate", "predictor": 3,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(result.probability, 1)
        dst.set_band_description(1, "probability_72h")
        dst.update_tags(METHOD="model b", RAIN_SOURCE=result.rain.source)


def main() -> None:
    started = time.perf_counter()
    rain = get_hourly_rain()
    fetched = time.perf_counter()
    result = run(rain)
    scored = time.perf_counter()
    signal, stats = result.rain, summarize(result.probability)

    print(f"rain ({signal.source}): past 72 h {signal.past_72h_mm} mm, past 7 days {signal.past_7d_mm} mm, "
          f"next 24 h {signal.next_24h_mm} mm, next 72 h {signal.next_72h_mm} mm")
    print(f"rainfall exceedance {signal.exceedance:+.2f} (worst {signal.worst_duration_h} h at "
          f"{signal.threshold_ratio}x the threshold), moisture index {signal.moisture_index}")
    print(f"probability over {stats['cells']} cells: min {stats['min']}, mean {stats['mean']}, max {stats['max']}")
    print("share by level: " + ", ".join(f"{level} {share:.0%}" for level, share in stats["share"].items()))
    print(f"overall level at the 99th percentile cell: {risk_level(float(np.nanpercentile(result.probability, 99)))}")

    again = time.perf_counter()
    run()  # a retry within the cache window skips the network
    print(f"time: fetch {fetched - started:.2f} s, score {scored - fetched:.2f} s, "
          f"cached rerun {time.perf_counter() - again:.2f} s")


if __name__ == "__main__":
    main()
