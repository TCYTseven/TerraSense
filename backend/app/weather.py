"""Hourly precipitation for Mount Rainier from Open-Meteo, cached for a few minutes.

The probability map (app/ml/probability.py, and Model B once step 17 lands), the Weather
Analyst's get_weather tool, and the panel's rain lines all read it. Open-Meteo needs no key.
Set OPEN_METEO_FIXTURE to a saved response to work offline; the result then says source
"fixture" so nothing downstream mistakes it for observed weather.
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.config import REPO_ROOT

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Shared facts: the Rainier peak.
PEAK_LAT, PEAK_LON = 46.8523, -121.7603
# At the 4392 m summit nearly all precipitation falls as snow. Ask Open-Meteo to downscale
# to Paradise (1650 m), where the trails are and where rain triggers debris flows.
TRAIL_ZONE_ELEVATION_M = 1650

PAST_DAYS = 7  # antecedent moisture needs a week
FORECAST_DAYS = 4  # today plus three, so the next 72 hours are always covered
CACHE_SECONDS = 300  # a demo retry within five minutes reuses the last response
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class HourlyRain:
    """Hourly precipitation (mm) with the index of the current hour."""

    times: list[datetime]
    precipitation_mm: list[float]
    now_index: int
    source: str  # "open-meteo" or "fixture"
    fetched_at: datetime

    def total(self, start_hour: int, end_hour: int) -> float:
        """Sum over [now + start_hour, now + end_hour). Negative hours are the past."""
        lo = max(0, self.now_index + start_hour)
        hi = min(len(self.precipitation_mm), self.now_index + end_hour)
        return float(sum(self.precipitation_mm[lo:hi]))


_cache: dict[str, tuple[float, HourlyRain]] = {}


def _parse(payload: dict, source: str, now: datetime) -> HourlyRain:
    hourly = payload["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
    values = [float(v or 0.0) for v in hourly["precipitation"]]
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    now_index = next((i for i, t in enumerate(times) if t >= now_hour), len(times))
    return HourlyRain(times, values, now_index, source, datetime.now(UTC))


def _load_fixture(path: Path) -> HourlyRain:
    """A saved response. Its timeline is shifted so its "fixture_now" hour is the current hour."""
    payload = json.loads(path.read_text())
    fixture_now = datetime.fromisoformat(payload["fixture_now"]).replace(tzinfo=UTC)
    now_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    shift = now_hour - fixture_now
    payload["hourly"]["time"] = [
        (datetime.fromisoformat(t) + shift).strftime("%Y-%m-%dT%H:%M") for t in payload["hourly"]["time"]
    ]
    return _parse(payload, "fixture", now_hour)


def get_hourly_rain(lat: float = PEAK_LAT, lon: float = PEAK_LON) -> HourlyRain:
    """Past week and next four days of hourly precipitation. Cached for CACHE_SECONDS."""
    fixture = os.environ.get("OPEN_METEO_FIXTURE", "").strip()
    if fixture:
        # Relative paths are from the repo root, like every other path in .env.
        path = Path(fixture)
        return _load_fixture(path if path.is_absolute() else REPO_ROOT / path)

    key = f"{lat:.4f},{lon:.4f}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    params = {
        "latitude": lat,
        "longitude": lon,
        "elevation": TRAIL_ZONE_ELEVATION_M,
        "hourly": "precipitation",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
    }
    response = httpx.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    rain = _parse(response.json(), "open-meteo", datetime.now(UTC))
    _cache[key] = (time.monotonic(), rain)
    return rain


def try_hourly_rain(lat: float = PEAK_LAT, lon: float = PEAK_LON) -> tuple[HourlyRain | None, str | None]:
    """get_hourly_rain(), or (None, why) when Open-Meteo or the fixture cannot give an answer."""
    try:
        return get_hourly_rain(lat, lon), None
    except httpx.HTTPStatusError as exc:
        return None, f"Open-Meteo answered HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        return None, f"Open-Meteo did not answer ({type(exc).__name__})"
    except (OSError, ValueError, KeyError) as exc:
        return None, f"the rain data could not be read ({type(exc).__name__}: {exc})"


def daily_totals_before_now(rain: HourlyRain, days: int) -> list[float]:
    """Totals for each of the last `days` 24-hour periods, most recent first."""
    return [rain.total(-24 * (d + 1), -24 * d) for d in range(days)]


def window_hours(rain: HourlyRain, back_hours: int, ahead_hours: int) -> list[float]:
    """Hourly values from now - back_hours to now + ahead_hours, clipped to the data."""
    lo = max(0, rain.now_index - back_hours)
    hi = min(len(rain.precipitation_mm), rain.now_index + ahead_hours)
    return rain.precipitation_mm[lo:hi]


def as_of(rain: HourlyRain) -> datetime:
    """The hour the totals are measured from."""
    if rain.now_index < len(rain.times):
        return rain.times[rain.now_index]
    return rain.times[-1] + timedelta(hours=1)


@dataclass(frozen=True)
class RainSummary:
    """Rain totals around now, in millimeters: what the Weather Analyst and the panel read."""

    source: str  # "open-meteo" or "fixture"
    as_of: datetime
    past_24h_mm: float
    past_72h_mm: float
    past_7d_mm: float
    next_24h_mm: float
    next_72h_mm: float
    max_hourly_next_72h_mm: float


def summarize(rain: HourlyRain) -> RainSummary:
    """Totals for the windows the agents and the panel talk about."""
    ahead = window_hours(rain, 0, 72)
    return RainSummary(
        source=rain.source,
        as_of=as_of(rain),
        past_24h_mm=round(rain.total(-24, 0), 1),
        past_72h_mm=round(rain.total(-72, 0), 1),
        past_7d_mm=round(rain.total(-168, 0), 1),
        next_24h_mm=round(rain.total(0, 24), 1),
        next_72h_mm=round(rain.total(0, 72), 1),
        max_hourly_next_72h_mm=round(max(ahead, default=0.0), 1),
    )
