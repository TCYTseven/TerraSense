"""Fetch historical hourly weather for event clusters and matched controls, and build the feature table.

`python ml/scripts/event_rain.py [--events PATH] [--controls-per-case K] [--offline] [--susceptibility-raster PATH]`

Case-crossover design. Each event cluster (from `event_catalog.py`) is a case at its weather cell
with reference time T = event day 00:00 UTC minus a lead (0, 24, or 48 h; the event day is local
Pacific time, so [T, T + 72 h) always contains it). Its controls are the same cell at other
times: one fixed random day per (year, calendar month), drawn from other years in the same
calendar month, never within `EXCLUSION_DAYS` of any dated landslide record within
`EXCLUSION_RADIUS_KM` (any type, trigger, or location accuracy), and never reused by another
case in the same cell. Location is constant within a matched set, so terrain susceptibility
cancels out of the rain comparison.

Weather is the Open-Meteo archive (ERA5 / ERA5-Land reanalysis, default `best_match`) at the
cell center, fetched in windows of at most 14 days (Open-Meteo counts anything longer as
several calls) with many cells per request, and cached per cell and window under
`data/raw/open_meteo_archive/`. The "next 72 h" rain here is reanalysis, so it is a
perfect-forecast upper bound on what the live forecast can do.

Writes `data/processed/events/features.parquet` (one row per sample and lead) and
`fetch_log.json` (requests made, weighted-call estimate).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO_ROOT / "data" / "processed" / "events"
CACHE_DIR = REPO_ROOT / "data" / "raw" / "open_meteo_archive"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = ["precipitation", "temperature_2m", "snowfall", "soil_moisture_0_to_7cm"]

# Model B rain math, copied from backend/app/ml/model_b.py (rain_signals and its constants).
# ml/tests/test_event_rain.py imports the backend module and asserts these stay equal.
GUZZETTI_A = 2.20
GUZZETTI_B = -0.44
RAINFALL_WINDOW_HOURS = 72
MOISTURE_WINDOW_HOURS = 168
RAINFALL_THRESHOLD_72H_MM = GUZZETTI_A * RAINFALL_WINDOW_HOURS**GUZZETTI_B * RAINFALL_WINDOW_HOURS
MOISTURE_THRESHOLD_7D_MM = GUZZETTI_A * MOISTURE_WINDOW_HOURS**GUZZETTI_B * MOISTURE_WINDOW_HOURS

LEADS_HOURS = (0, 24, 48)  # T = event day 00:00 UTC minus this; 48 h keeps the event inside [T, T+72h)
WINDOW_BEFORE_DAYS = 9  # 7-day antecedent window at the longest lead
WINDOW_AFTER_DAYS = 3  # the 72 hours from the event day
MAX_REQUEST_DAYS = 14  # Open-Meteo counts longer spans per location as more than one call
CONTROLS_PER_CASE = 4
EXCLUSION_DAYS = 7  # no control within this many days of a dated landslide nearby
EXCLUSION_RADIUS_KM = 25.0  # covers the neighboring 0.1 degree cells
MONTH_OFFSETS = (0, -1, 1)  # control calendar month relative to the case, tried in this order
SNOW_WATER_MM_PER_CM = 10.0 / 7.0  # Open-Meteo: 7 cm of snowfall is 10 mm of water
SEED = 20260926
LOCATIONS_PER_REQUEST = 100
REQUEST_PAUSE_S = 1.0
TIMEOUT_S = 120
MAX_RETRIES = 6


def bounded_signed_ratio(total_mm: float, threshold_mm: float) -> float:
    """Same as model_b._bounded_signed_ratio: -1..1, zero at the threshold."""
    if threshold_mm <= 0:
        return 0.0
    return float(np.clip(total_mm / threshold_mm - 1.0, -1.0, 1.0))


def window_total(values: np.ndarray, now_index: int, start_hour: int, end_hour: int) -> float:
    """Same as HourlyRain.total: sum over [now + start, now + end), clipped to the series."""
    lo = max(0, now_index + start_hour)
    hi = min(len(values), now_index + end_hour)
    return float(np.sum(values[lo:hi]))


def model_b_signals(precip_mm: np.ndarray, now_index: int) -> dict[str, float]:
    """The Model B rain signals at one reference hour, as model_b.rain_signals computes them."""
    past_72h = window_total(precip_mm, now_index, -RAINFALL_WINDOW_HOURS, 0)
    next_72h = window_total(precip_mm, now_index, 0, RAINFALL_WINDOW_HOURS)
    past_7d = window_total(precip_mm, now_index, -MOISTURE_WINDOW_HOURS, 0)
    return {
        "past_72h_mm": past_72h,
        "next_72h_mm": next_72h,
        "past_7d_mm": past_7d,
        "rainfall_exceedance": bounded_signed_ratio(next_72h, RAINFALL_THRESHOLD_72H_MM),
        "moisture_index": bounded_signed_ratio(past_7d, MOISTURE_THRESHOLD_7D_MM),
    }


def rich_features(hourly: pd.DataFrame, now_index: int) -> dict[str, float]:
    """Model B signals plus candidate rain, snow, and soil features at one reference hour.

    Names with `next_` use hours at or after T (the perfect-forecast part); every other feature
    uses only hours before T.
    """
    precip = hourly.precipitation.to_numpy(dtype=float)
    snow_cm = hourly.snowfall.to_numpy(dtype=float)
    temp = hourly.temperature_2m.to_numpy(dtype=float)
    soil = hourly.soil_moisture_0_to_7cm.to_numpy(dtype=float)
    liquid = np.clip(precip - snow_cm * SNOW_WATER_MM_PER_CM, 0.0, None)
    out = model_b_signals(precip, now_index)
    out["past_72h_exceedance"] = bounded_signed_ratio(out["past_72h_mm"], RAINFALL_THRESHOLD_72H_MM)
    out["past_24h_mm"] = window_total(precip, now_index, -24, 0)
    past = precip[max(0, now_index - MOISTURE_WINDOW_HOURS):now_index]
    ahead = precip[now_index:now_index + RAINFALL_WINDOW_HOURS]
    out["max_24h_past_7d_mm"] = float(pd.Series(past).rolling(24).sum().max()) if len(past) >= 24 else np.nan
    out["max_24h_next_72h_mm"] = float(pd.Series(ahead).rolling(24).sum().max()) if len(ahead) >= 24 else np.nan
    out["max_1h_next_72h_mm"] = float(np.max(ahead)) if len(ahead) else np.nan
    out["snowfall_past_7d_cm"] = window_total(snow_cm, now_index, -MOISTURE_WINDOW_HOURS, 0)
    out["liquid_next_72h_mm"] = window_total(liquid, now_index, 0, RAINFALL_WINDOW_HOURS)
    out["liquid_past_72h_mm"] = window_total(liquid, now_index, -RAINFALL_WINDOW_HOURS, 0)
    # Rain on a fresh snowpack: liquid rain falling within a week of snowfall.
    out["rain_on_snow_next_72h_mm"] = out["liquid_next_72h_mm"] if out["snowfall_past_7d_cm"] >= 1.0 else 0.0
    out["rain_on_snow_past_72h_mm"] = out["liquid_past_72h_mm"] if out["snowfall_past_7d_cm"] >= 1.0 else 0.0
    out["temp_mean_past_72h_c"] = float(np.nanmean(temp[max(0, now_index - 72):now_index])) \
        if now_index > 0 and np.isfinite(temp[max(0, now_index - 72):now_index]).any() else np.nan
    out["temp_mean_next_72h_c"] = float(np.nanmean(ahead_t)) if len(ahead_t := temp[now_index:now_index + 72]) \
        and np.isfinite(ahead_t).any() else np.nan
    out["soil_moisture_at_t"] = float(soil[now_index - 1]) if now_index > 0 and np.isfinite(soil[now_index - 1]) \
        else np.nan
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def control_slots(start_year: int, end_year: int, rng: np.random.Generator) -> dict[tuple[int, int], pd.Timestamp]:
    """One fixed random day per (year, month): every cell drawing that slot shares one request."""
    slots = {}
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            days = pd.Timestamp(year=year, month=month, day=1).days_in_month
            slots[(year, month)] = pd.Timestamp(year=year, month=month, day=int(rng.integers(1, days + 1)))
    return slots


def blocked_intervals(cell_lat: float, cell_lon: float, blockers: pd.DataFrame,
                      radius_km: float = EXCLUSION_RADIUS_KM, days: int = EXCLUSION_DAYS) -> np.ndarray:
    """[start, end] day intervals (int64 days since epoch) where no control may sit at this cell."""
    near = blockers[haversine_km(cell_lat, cell_lon, blockers.lat.to_numpy(), blockers.lon.to_numpy()) <= radius_km]
    start = (near.start - pd.Timedelta(days=days)).to_numpy("datetime64[D]").astype(np.int64)
    end = (near.end + pd.Timedelta(days=days)).to_numpy("datetime64[D]").astype(np.int64)
    return np.stack([start, end], axis=1) if len(near) else np.zeros((0, 2), dtype=np.int64)


def is_blocked(day: pd.Timestamp, intervals: np.ndarray) -> bool:
    d = np.datetime64(day.date(), "D").astype(np.int64)
    return bool(((intervals[:, 0] <= d) & (d <= intervals[:, 1])).any()) if len(intervals) else False


def draw_controls(clusters: pd.DataFrame, blockers: pd.DataFrame, k: int, start_year: int, end_year: int,
                  seed: int = SEED) -> pd.DataFrame:
    """Matched controls: same cell, same calendar month, other years, clear of nearby landslides."""
    rng = np.random.default_rng(seed)
    slots = control_slots(start_year, end_year, rng)
    last_ok = pd.Timestamp(year=end_year, month=12, day=31) - pd.Timedelta(days=WINDOW_AFTER_DAYS)
    first_ok = pd.Timestamp(year=start_year, month=1, day=1) + pd.Timedelta(days=WINDOW_BEFORE_DAYS)
    intervals = {cell: blocked_intervals(g.cell_lat.iloc[0], g.cell_lon.iloc[0], blockers)
                 for cell, g in clusters.groupby("cell_id")}
    used: dict[str, set] = {}
    rows = []
    for c in clusters.sort_values(["date", "cluster_id"]).itertuples():
        taken = used.setdefault(c.cell_id, set())
        n = 0
        # Same calendar month first; the neighboring months only once a dense cell has used it up.
        for month_offset in MONTH_OFFSETS:
            years = [y for y in range(start_year, end_year + 1) if y != c.date.year]
            rng.shuffle(years)
            month = (c.date.month - 1 + month_offset) % 12 + 1
            for year in years:
                day = slots[(year, month)]
                if day in taken or not (first_ok <= day <= last_ok) or is_blocked(day, intervals[c.cell_id]):
                    continue
                taken.add(day)
                rows.append({"cluster_id": c.cluster_id, "cell_id": c.cell_id, "cell_lat": c.cell_lat,
                             "cell_lon": c.cell_lon, "day": day, "role": "control",
                             "month_offset": month_offset})
                n += 1
                if n == k:
                    break
            if n == k:
                break
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def case_windows(days: list[pd.Timestamp]) -> dict[pd.Timestamp, Window]:
    """Merge nearby case days into shared request windows no longer than MAX_REQUEST_DAYS."""
    out: dict[pd.Timestamp, Window] = {}
    group: list[pd.Timestamp] = []

    def close(group):
        w = Window((group[0] - pd.Timedelta(days=WINDOW_BEFORE_DAYS)).date(),
                   (group[-1] + pd.Timedelta(days=WINDOW_AFTER_DAYS - 1)).date())
        for d in group:
            out[d] = w

    for day in sorted(set(days)):
        span = WINDOW_BEFORE_DAYS + WINDOW_AFTER_DAYS + ((day - group[0]).days if group else 0)
        if group and span > MAX_REQUEST_DAYS:
            close(group)
            group = []
        group.append(day)
    if group:
        close(group)
    return out


def cache_path(cell_lat: float, cell_lon: float, window: Window, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"{cell_lat:.4f}_{cell_lon:.4f}_{window.start:%Y%m%d}_{window.end:%Y%m%d}.json"


class Fetcher:
    """Batched, cached, polite Open-Meteo archive client."""

    def __init__(self, offline: bool, cache_dir: Path = CACHE_DIR) -> None:
        self.offline = offline
        self.cache_dir = cache_dir
        self.http_requests = 0
        self.weighted_calls = 0.0
        self.retries = 0
        self.session = requests.Session()

    def ensure(self, window: Window, cells: list[tuple[float, float]]) -> None:
        missing = [c for c in cells if not cache_path(*c, window, self.cache_dir).is_file()]
        if not missing:
            return
        if self.offline:
            raise FileNotFoundError(f"{len(missing)} cells missing from the cache for {window} (--offline)")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(missing), LOCATIONS_PER_REQUEST):
            chunk = missing[i:i + LOCATIONS_PER_REQUEST]
            payload = self._get(window, chunk)
            items = payload if isinstance(payload, list) else [payload]
            if len(items) != len(chunk):
                raise ValueError(f"asked for {len(chunk)} locations, got {len(items)}")
            for (lat, lon), item in zip(chunk, items):
                item["requested"] = {"latitude": lat, "longitude": lon, "start_date": str(window.start),
                                     "end_date": str(window.end), "url": ARCHIVE_URL}
                path = cache_path(lat, lon, window, self.cache_dir)
                tmp = path.with_suffix(".part")
                tmp.write_text(json.dumps(item))
                tmp.replace(path)

    def _get(self, window: Window, chunk: list[tuple[float, float]]):
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in chunk),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in chunk),
            "start_date": str(window.start), "end_date": str(window.end),
            "hourly": ",".join(HOURLY_VARS), "timezone": "UTC",
        }
        delay = 30.0
        for attempt in range(MAX_RETRIES):
            time.sleep(REQUEST_PAUSE_S)
            self.http_requests += 1
            try:
                response = self.session.get(ARCHIVE_URL, params=params, timeout=TIMEOUT_S)
            except requests.RequestException:
                response = None
            if response is not None and response.status_code == 200:
                self.weighted_calls += len(chunk) * max(1.0, window.days / MAX_REQUEST_DAYS)
                return response.json()
            status = None if response is None else response.status_code
            if status is not None and status not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Open-Meteo HTTP {status}: {response.text[:300]}")
            self.retries += 1
            print(f"  HTTP {status}; retry {attempt + 1} in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 600)
        raise RuntimeError(f"Open-Meteo failed after {MAX_RETRIES} attempts for {window}")


def load_hourly(path: Path) -> pd.DataFrame:
    item = json.loads(path.read_text())
    hourly = item["hourly"]
    frame = pd.DataFrame({var: pd.to_numeric(pd.Series(hourly.get(var, [np.nan] * len(hourly["time"]))),
                                             errors="coerce") for var in HOURLY_VARS})
    frame.index = pd.to_datetime(hourly["time"])
    frame["precipitation"] = frame.precipitation.fillna(0.0)  # as backend weather._parse
    frame["snowfall"] = frame.snowfall.fillna(0.0)
    frame.attrs["grid_lat"] = item.get("latitude")
    frame.attrs["grid_lon"] = item.get("longitude")
    frame.attrs["grid_elevation"] = item.get("elevation")
    return frame


def sample_susceptibility(raster: Path, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Susceptibility at each point from a GeoTIFF in any CRS; NaN outside it or on nodata."""
    import rasterio
    from rasterio.warp import transform as warp_transform

    with rasterio.open(raster) as src:
        xs, ys = warp_transform("EPSG:4326", src.crs, list(lons), list(lats))
        values = np.array([v[0] for v in src.sample(zip(xs, ys), masked=True)], dtype="float64")
        nodata = src.nodata
    values = np.where(np.isfinite(values), values, np.nan)
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--events", type=Path, default=EVENTS_DIR / "events.parquet")
    parser.add_argument("--blockers", type=Path, default=EVENTS_DIR / "exclusion_records.parquet")
    parser.add_argument("--controls-per-case", type=int, default=CONTROLS_PER_CASE)
    parser.add_argument("--start-year", type=int, default=1980)
    parser.add_argument("--end-year", type=int, default=2023)
    parser.add_argument("--offline", action="store_true", help="use only cached archive responses")
    parser.add_argument("--susceptibility-raster", type=Path, default=None,
                        help="GeoTIFF of 0-1 susceptibility; sampled at each cluster centroid (optional)")
    parser.add_argument("--plan", action="store_true", help="print the sample and request plan, fetch nothing")
    parser.add_argument("--out", type=Path, default=EVENTS_DIR / "features.parquet")
    args = parser.parse_args(argv)
    started = time.monotonic()

    clusters = pd.read_parquet(args.events)
    blockers = pd.read_parquet(args.blockers)
    controls = draw_controls(clusters, blockers, args.controls_per_case, args.start_year, args.end_year)
    cases = clusters.assign(day=clusters.date, role="case", month_offset=0)[
        ["cluster_id", "cell_id", "cell_lat", "cell_lon", "day", "role", "month_offset"]]
    samples = pd.concat([cases, controls], ignore_index=True)
    meta = clusters.set_index("cluster_id")[["storm_id", "water_year", "date", "lat", "lon", "n_records",
                                             "sources", "inventories"]]
    samples = samples.join(meta, on="cluster_id")
    samples = samples.rename(columns={"date": "case_date"})
    samples["sample_id"] = samples.cell_id + "@" + samples.day.dt.strftime("%Y-%m-%d")
    if samples.sample_id.duplicated().any():
        raise ValueError("a (cell, day) sample belongs to two matched sets")

    windows = case_windows(list(cases.day))
    samples["window"] = [windows[d] if r == "case" else
                         Window((d - pd.Timedelta(days=WINDOW_BEFORE_DAYS)).date(),
                                (d + pd.Timedelta(days=WINDOW_AFTER_DAYS - 1)).date())
                         for d, r in zip(samples.day, samples.role)]
    samples["window_key"] = samples.window.map(lambda w: (w.start, w.end))
    groups = samples.groupby("window_key", sort=True)
    n_missing = sum(not cache_path(r.cell_lat, r.cell_lon, r.window).is_file()
                    for r in samples.drop_duplicates(["cell_id", "window_key"]).itertuples())
    print(f"{len(cases)} cases, {len(controls)} controls, {groups.ngroups} request windows, "
          f"{n_missing} (cell, window) series not cached", flush=True)
    if args.plan:
        return 0
    fetcher = Fetcher(args.offline)
    for i, (key, g) in enumerate(groups):
        window = Window(*key)
        cells = sorted(set(zip(g.cell_lat, g.cell_lon)))
        before = fetcher.http_requests
        fetcher.ensure(window, cells)
        if fetcher.http_requests != before and (i % 25 == 0):
            print(f"  window {i + 1}/{groups.ngroups} {window.start}..{window.end}: {len(cells)} cells, "
                  f"{fetcher.http_requests} requests so far", flush=True)

    rows = []
    for s in samples.itertuples():
        hourly = load_hourly(cache_path(s.cell_lat, s.cell_lon, s.window))
        for lead in LEADS_HOURS:
            t = s.day - pd.Timedelta(hours=lead)
            now_index = int(hourly.index.searchsorted(t))
            if hourly.index[now_index] != t or now_index < MOISTURE_WINDOW_HOURS \
                    or now_index + RAINFALL_WINDOW_HOURS > len(hourly):
                raise ValueError(f"window {s.window} does not cover {t} for {s.sample_id}")
            rows.append({"sample_id": s.sample_id, "lead_hours": lead, "reference_time": t,
                         "grid_lat": hourly.attrs["grid_lat"], "grid_lon": hourly.attrs["grid_lon"],
                         "grid_elevation_m": hourly.attrs["grid_elevation"], **rich_features(hourly, now_index)})
    feats = pd.DataFrame(rows)
    table = samples.drop(columns=["window", "window_key"]).merge(feats, on="sample_id")
    table["label"] = (table.role == "case").astype(int)
    table["sample_water_year"] = table.day.dt.year + (table.day.dt.month >= 10).astype(int)
    table["susceptibility"] = np.nan
    if args.susceptibility_raster:
        table["susceptibility"] = sample_susceptibility(args.susceptibility_raster, table.lat.to_numpy(),
                                                        table.lon.to_numpy())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    per_set = table[table.lead_hours == 0].groupby("cluster_id").label.agg(["sum", "size"])
    log = {
        "archive_url": ARCHIVE_URL, "hourly": HOURLY_VARS, "model": "best_match (ERA5 / ERA5-Land)",
        "http_requests_this_run": fetcher.http_requests, "retries_this_run": fetcher.retries,
        "weighted_calls_this_run_estimate": fetcher.weighted_calls,
        "cached_files": len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.is_dir() else 0,
        "request_windows": groups.ngroups, "n_cases": int(len(cases)), "n_controls": int(len(controls)),
        "controls_per_case_requested": args.controls_per_case,
        "cases_with_fewer_controls": int((per_set["size"] - 1 < args.controls_per_case).sum()),
        "susceptibility_raster": str(args.susceptibility_raster) if args.susceptibility_raster else None,
        "runtime_s": round(time.monotonic() - started, 1),
    }
    log_path = args.out.with_name("fetch_log.json")
    previous = json.loads(log_path.read_text()) if log_path.is_file() else {}
    log["http_requests_cumulative"] = previous.get("http_requests_cumulative", 0) + fetcher.http_requests
    log["weighted_calls_cumulative_estimate"] = previous.get("weighted_calls_cumulative_estimate", 0) \
        + fetcher.weighted_calls
    log_path.write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))
    print(f"wrote {args.out} ({len(table)} rows = samples x {len(LEADS_HOURS)} leads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
