"""Model B: turn terrain susceptibility and rain into a 72-hour landslide risk index.

This is the live trigger layer on top of the offline susceptibility raster. It is deliberately
small and vectorized so a new Open-Meteo response can be scored in milliseconds after the
GeoTIFF is opened.

The index is sigmoid(W1 * logit(susceptibility) + W0 + W2 * rainfall_exceedance + W3 * moisture_index).
Terrain odds come from the susceptibility raster, calibrated with slide pixels sampled 1:3 against
stable ones (ml/artifacts/metrics.json). Rain odds come from a logistic fit on 767 dated landslides,
calibrated with slide days sampled 1:4 against quiet days in the same place
(ml/artifacts/model_b_validation.json). Their product assumes terrain and rain act independently.
Both parts are validated for ranking places and days; the absolute level depends on the sampling
ratios, so the output is a relative index, not a probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from app.config import REPO_ROOT
from app.weather import HourlyRain

SUSCEPTIBILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"

# Model B weights. W0, W2, W3: logistic fit on 767 dated PNW landslides, storm-bootstrap 95% CIs.
# The artifact's publish rule is not met: ROC-AUC is 0.005 below the hand-set weights (95% CI
# -0.007 to -0.002), but calibration error falls from 0.189 to 0.032, and the index is binned.
W1 = 1.0  # Terrain enters as the log-odds of calibrated susceptibility, unscaled.
W0 = -1.32  # Rain odds on a day at both reference thresholds, 95% CI -1.51 to -1.18.
W2 = 0.92  # Forecast rain over the 72-hour threshold, 95% CI 0.74-1.10 (hand-set 2.0).
W3 = 0.76  # Past-week rain over the 7-day threshold, 95% CI 0.59-0.93 (hand-set 1.6).

# Keeps logit() finite at susceptibility 0 or 1.
SUSCEPTIBILITY_CLIP = 1e-3

# Guzzetti et al. (2008) reference: I = 2.20 * D^-0.44 mm/h, converted to a D-hour total.
GUZZETTI_A = 2.20
GUZZETTI_B = -0.44
RAINFALL_WINDOW_HOURS = 72
MOISTURE_WINDOW_HOURS = 168
RAINFALL_THRESHOLD_72H_MM = GUZZETTI_A * RAINFALL_WINDOW_HOURS**GUZZETTI_B * RAINFALL_WINDOW_HOURS
MOISTURE_THRESHOLD_7D_MM = GUZZETTI_A * MOISTURE_WINDOW_HOURS**GUZZETTI_B * MOISTURE_WINDOW_HOURS


@dataclass(frozen=True)
class RainSignals:
    """Rain totals and the two bounded signals used by Model B."""

    past_72h_mm: float
    next_72h_mm: float
    past_7d_mm: float
    rainfall_exceedance: float
    moisture_index: float


@dataclass(frozen=True)
class ModelBResult:
    """The probability raster plus the georeferencing needed by the shared seam."""

    probability: np.ndarray
    transform: Affine
    crs: str


def _bounded_signed_ratio(total_mm: float, threshold_mm: float) -> float:
    """Return a stable -1..1 signal centered on the reference threshold."""
    if threshold_mm <= 0:
        return 0.0
    return float(np.clip(total_mm / threshold_mm - 1.0, -1.0, 1.0))


def rain_signals(rain: HourlyRain | None) -> RainSignals:
    """Convert one hourly response into normalized forecast-rain and moisture signals.

    Missing rain is an explicit dry/neutral fallback: the run still scores terrain, but it does
    not silently fetch the network a second time or pretend that rain was observed.
    """
    if rain is None:
        return RainSignals(0.0, 0.0, 0.0, -1.0, -1.0)

    past_72h = rain.total(-RAINFALL_WINDOW_HOURS, 0)
    next_72h = rain.total(0, RAINFALL_WINDOW_HOURS)
    past_7d = rain.total(-MOISTURE_WINDOW_HOURS, 0)
    return RainSignals(
        past_72h_mm=past_72h,
        next_72h_mm=next_72h,
        past_7d_mm=past_7d,
        rainfall_exceedance=_bounded_signed_ratio(next_72h, RAINFALL_THRESHOLD_72H_MM),
        moisture_index=_bounded_signed_ratio(past_7d, MOISTURE_THRESHOLD_7D_MM),
    )


def contributions(susceptibility: float, rain: HourlyRain | None) -> dict[str, float]:
    """Each input's term in the logit at one cell, and the rain totals behind the two rain terms."""
    signals = rain_signals(rain)
    return {
        "terrain": float(W1 * _logit(np.float64(susceptibility))),
        "rain_baseline": W0,
        "forecast_rain": W2 * signals.rainfall_exceedance,
        "antecedent_moisture": W3 * signals.moisture_index,
        "past_72h_mm": signals.past_72h_mm,
        "next_72h_mm": signals.next_72h_mm,
        "past_7d_mm": signals.past_7d_mm,
        "threshold_72h_mm": RAINFALL_THRESHOLD_72H_MM,
        "threshold_7d_mm": MOISTURE_THRESHOLD_7D_MM,
    }


def _logit(susceptibility: np.ndarray) -> np.ndarray:
    clipped = np.clip(susceptibility, SUSCEPTIBILITY_CLIP, 1.0 - SUSCEPTIBILITY_CLIP)
    return np.log(clipped / (1.0 - clipped))


def sigmoid(values: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid for a raster-sized array."""
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        return 1.0 / (1.0 + np.exp(-np.clip(values, -60.0, 60.0)))


def _read_susceptibility(path: Path) -> tuple[np.ndarray, Affine, str]:
    if not path.is_file():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise FileNotFoundError(
            f"{display_path} is missing (susceptibility GeoTIFF). "
            "From repo root: python ml/scripts/download_sources.py --only dem,landcover && "
            "python ml/scripts/build_features.py && python ml/scripts/train_susceptibility.py"
        )
    with rasterio.open(path) as src:
        masked = src.read(1, masked=True).astype("float32")
        values = np.asarray(masked.filled(np.nan), dtype="float32")
        crs = src.crs.to_string() if src.crs else ""
        return values, src.transform, crs


def run(rain: HourlyRain | None = None, path: Path | None = None) -> ModelBResult:
    """Return the 72-hour landslide risk index map for the current rain response.

    The three inputs are terrain log-odds, forecast rainfall exceedance, and
    antecedent moisture. Invalid or nodata susceptibility cells stay NaN so the tile renderer
    and hazard sampler never turn outside-the-box pixels into risk.
    """
    susceptibility, transform, crs = _read_susceptibility(path or SUSCEPTIBILITY_PATH)
    signals = rain_signals(rain)
    valid = np.isfinite(susceptibility)
    with np.errstate(invalid="ignore"):
        terrain = _logit(susceptibility)
    logit = (
        W1 * terrain
        + W0
        + W2 * signals.rainfall_exceedance
        + W3 * signals.moisture_index
    )
    probability = np.full(susceptibility.shape, np.nan, dtype="float32")
    probability[valid] = sigmoid(logit[valid]).astype("float32")
    return ModelBResult(probability=probability, transform=transform, crs=crs)
