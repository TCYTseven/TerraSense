"""Hourly weather for Mount Rainier from Open-Meteo, cached for a few minutes.

Precipitation drives the hazard model. The other series are context the agents read: temperature
and the freezing level decide whether the next storm falls as rain on bare ground or as snow,
freeze-thaw cycles loosen rock, soil moisture says how much water the ground can still take, and
wind is a hiking-conditions fact the ranger response quotes.

The probability map (app/ml/probability.py, and Model B once step 17 lands), the Weather
Analyst's get_weather tool, and the panel's rain lines all read it. Open-Meteo needs no key.
Set OPEN_METEO_FIXTURE to a saved response to work offline; the result then says source
"fixture" so nothing downstream mistakes it for observed weather.

When Open-Meteo stops answering mid-demo, the last good response is served again, from memory
or from its copy on disk, with source "open-meteo (cached)". With no good response at all, a
file named in OPEN_METEO_FALLBACK_FIXTURE is loaded as source "fixture". Both are labeled, so
the agents and the panel say what they are reading.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.config import REPO_ROOT
from app.risk import LIVE_PEAK_LAT, LIVE_PEAK_LON

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Shared facts: the Rainier peak.
PEAK_LAT, PEAK_LON = LIVE_PEAK_LAT, LIVE_PEAK_LON
# At the 4392 m summit nearly all precipitation falls as snow. Ask Open-Meteo to downscale
# to Paradise (1650 m), where the trails are and where rain triggers debris flows.
TRAIL_ZONE_ELEVATION_M = 1650

PAST_DAYS = 7  # antecedent moisture needs a week
FORECAST_DAYS = 4  # today plus three, so the next 72 hours are always covered
CACHE_SECONDS = 300  # a demo retry within five minutes reuses the last response
TIMEOUT_SECONDS = 10
# The last good Open-Meteo response per point, so a venue network that drops mid-demo does not
# fail a run. Gitignored with the rest of data/processed/.
CACHE_DIR = REPO_ROOT / "data" / "processed" / "weather_cache"
CACHED_SOURCE = "open-meteo (cached)"


# The extra hourly series, and the field each one lands in. A saved fixture may carry only
# precipitation, so every one of these is optional everywhere downstream.
EXTRA_SERIES = {
    "temperature_2m": "temperature_c",
    "snowfall": "snowfall_cm",
    "wind_speed_10m": "wind_kmh",
    "soil_moisture_0_to_7cm": "soil_moisture",
    "freezing_level_height": "freezing_level_m",
}


@dataclass(frozen=True)
class HourlyRain:
    """Hourly precipitation (mm) with the index of the current hour, and the conditions around it."""

    times: list[datetime]
    precipitation_mm: list[float]
    now_index: int
    source: str  # "open-meteo", "open-meteo (cached)", or "fixture"
    fetched_at: datetime
    # Optional: present from Open-Meteo, absent from a fixture saved with precipitation only.
    temperature_c: list[float] = field(default_factory=list)
    snowfall_cm: list[float] = field(default_factory=list)
    wind_kmh: list[float] = field(default_factory=list)
    soil_moisture: list[float] = field(default_factory=list)
    freezing_level_m: list[float] = field(default_factory=list)

    def total(self, start_hour: int, end_hour: int) -> float:
        """Sum over [now + start_hour, now + end_hour). Negative hours are the past."""
        lo = max(0, self.now_index + start_hour)
        hi = min(len(self.precipitation_mm), self.now_index + end_hour)
        return float(sum(self.precipitation_mm[lo:hi]))

    def window(self, series: list[float], start_hour: int, end_hour: int) -> list[float]:
        """A slice of any hourly series over [now + start_hour, now + end_hour). Empty when absent."""
        if not series:
            return []
        lo = max(0, self.now_index + start_hour)
        hi = min(len(series), self.now_index + end_hour)
        return series[lo:hi]

    def at_now(self, series: list[float]) -> float | None:
        """The current hour's reading from any series, or None when the series is absent."""
        if not series:
            return None
        return series[min(self.now_index, len(series) - 1)]


_cache: dict[str, tuple[float, HourlyRain]] = {}
_payloads: dict[str, dict] = {}  # the raw last good response per point, for the stale fallback


def _series(values: list) -> list[float]:
    """One hourly series, keeping its length so its index still lines up with `times`.

    Two things go wrong if this is naive. Dropping a null hour shifts every later value by one
    and puts now_index on the wrong hour, so gaps are filled rather than removed: forward from
    the last reading, and backward from the first when the series opens with a gap.

    Filling a gap with 0.0 is worse than not answering. Open-Meteo returns soil moisture as all
    nulls at Paradise's elevation, and a zero there reads as bone-dry ground on a mountain that
    just took 61 mm of rain. A series with no readings at all comes back empty, which every
    reader downstream already treats as "this source did not carry it" and shows as null.
    """
    if all(value is None for value in values):
        return []
    out: list[float | None] = [None if value is None else float(value) for value in values]
    last: float | None = None
    for i, value in enumerate(out):  # forward-fill from the previous reading
        if value is None:
            out[i] = last
        else:
            last = value
    first = next(value for value in out if value is not None)
    return [first if value is None else value for value in out]  # back-fill a leading gap


def _parse(payload: dict, source: str, now: datetime) -> HourlyRain:
    hourly = payload["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
    values = [float(v or 0.0) for v in hourly["precipitation"]]
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    now_index = next((i for i, t in enumerate(times) if t >= now_hour), len(times))
    extras = {field_name: _series(hourly[key])
              for key, field_name in EXTRA_SERIES.items() if isinstance(hourly.get(key), list)}
    return HourlyRain(times, values, now_index, source, datetime.now(UTC), **extras)


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


def _env_path(name: str) -> Path | None:
    """A path from .env. Relative paths are from the repo root, like every other path there."""
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _disk_path(key: str) -> Path:
    return CACHE_DIR / f"{key.replace(',', '_')}.json"


def _save_to_disk(key: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        partial = _disk_path(key).with_suffix(".part")
        partial.write_text(json.dumps(payload))
        partial.replace(_disk_path(key))
    except OSError:
        pass  # the disk copy is a convenience; the live answer already came back


def _stale(key: str) -> HourlyRain | None:
    """The last good response for this point, from memory or disk, relabeled as cached.

    It is parsed again against the current hour, so "now" moves forward through the stored
    forecast instead of staying at the hour it was fetched.
    """
    payload = _payloads.get(key)
    if payload is None:
        try:
            payload = json.loads(_disk_path(key).read_text())
        except (OSError, ValueError):
            return None
    try:
        return _parse(payload, CACHED_SOURCE, datetime.now(UTC))
    except (ValueError, KeyError, TypeError):
        return None


def get_hourly_rain(lat: float = PEAK_LAT, lon: float = PEAK_LON) -> HourlyRain:
    """Past week and next four days of hourly precipitation. Cached for CACHE_SECONDS."""
    fixture = _env_path("OPEN_METEO_FIXTURE")
    if fixture is not None:
        return _load_fixture(fixture)

    key = f"{lat:.4f},{lon:.4f}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        return _fetch(lat, lon, key)
    except httpx.HTTPError:
        stale = _stale(key)
        if stale is not None:
            return stale
        fallback = _env_path("OPEN_METEO_FALLBACK_FIXTURE")
        if fallback is not None and fallback.is_file():
            return _load_fixture(fallback)
        raise


def _fetch(lat: float, lon: float, key: str) -> HourlyRain:

    params = {
        "latitude": lat,
        "longitude": lon,
        "elevation": TRAIL_ZONE_ELEVATION_M,
        "hourly": ",".join(["precipitation", *EXTRA_SERIES]),
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
    }
    response = httpx.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    rain = _parse(payload, "open-meteo", datetime.now(UTC))
    _cache[key] = (time.monotonic(), rain)
    _payloads[key] = payload
    _save_to_disk(key, payload)
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
    """Rain totals around now, in millimeters, and the conditions the agents quote alongside them.

    The rain fields are required: they drive the hazard. Everything after them is None when the
    source did not carry that series.
    """

    source: str  # "open-meteo" or "fixture"
    as_of: datetime
    past_24h_mm: float
    past_72h_mm: float
    past_7d_mm: float
    next_24h_mm: float
    next_72h_mm: float
    max_hourly_next_72h_mm: float
    temp_now_c: float | None = None
    temp_min_next_72h_c: float | None = None
    temp_max_next_72h_c: float | None = None
    freeze_thaw_cycles_next_72h: int | None = None
    snowfall_next_72h_cm: float | None = None
    wind_max_next_24h_kmh: float | None = None
    soil_moisture_now: float | None = None  # m3/m3 in the top 7 cm
    freezing_level_now_m: float | None = None


def freeze_thaw_cycles(temperatures: list[float]) -> int:
    """How many times the hourly temperature crosses 0 C and back: each cycle loosens rock and soil."""
    crossings = 0
    above = None
    for value in temperatures:
        now_above = value > 0
        if above is not None and now_above != above:
            crossings += 1
        above = now_above
    return crossings // 2


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def summarize(rain: HourlyRain) -> RainSummary:
    """Totals and conditions for the windows the agents and the panel talk about."""
    ahead = window_hours(rain, 0, 72)
    temps = rain.window(rain.temperature_c, 0, 72)
    return RainSummary(
        source=rain.source,
        as_of=as_of(rain),
        past_24h_mm=round(rain.total(-24, 0), 1),
        past_72h_mm=round(rain.total(-72, 0), 1),
        past_7d_mm=round(rain.total(-168, 0), 1),
        next_24h_mm=round(rain.total(0, 24), 1),
        next_72h_mm=round(rain.total(0, 72), 1),
        max_hourly_next_72h_mm=round(max(ahead, default=0.0), 1),
        temp_now_c=_round(rain.at_now(rain.temperature_c)),
        temp_min_next_72h_c=_round(min(temps) if temps else None),
        temp_max_next_72h_c=_round(max(temps) if temps else None),
        freeze_thaw_cycles_next_72h=freeze_thaw_cycles(temps) if temps else None,
        snowfall_next_72h_cm=_round(sum(rain.window(rain.snowfall_cm, 0, 72)) or 0.0) if rain.snowfall_cm else None,
        wind_max_next_24h_kmh=_round(max(rain.window(rain.wind_kmh, 0, 24), default=None)
                                     if rain.wind_kmh else None),
        soil_moisture_now=_round(rain.at_now(rain.soil_moisture), 3),
        freezing_level_now_m=_round(rain.at_now(rain.freezing_level_m), 0),
    )
