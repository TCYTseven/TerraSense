#!/usr/bin/env python3
"""Download as-of NOAA GEFS forecast features for dated avalanche samples.

The NOAA Open Data AWS buckets contain historical GRIB2 cycles, but a full global file is large.
This downloader reads the public ``.idx`` sidecar and uses HTTP byte ranges to fetch only the
individual GRIB messages needed for precipitation, snow-water-equivalent, temperature, and wind.
It writes a long parquet table that can be joined to the canonical avalanche feature builder.

The reference time is treated as an operational availability time.  The default six-hour lag
selects the latest model cycle that would reasonably have been available before that time.  For a
reference at 00Z, this therefore uses the prior 18Z cycle rather than accidentally using a run
that was not available yet.

The GEFS ``geavg`` and ``gespr`` products are used instead of pretending one ensemble member is
the truth.  The snowfall p90/p95 fields downstream are explicitly marked as Gaussian summary
proxies because the downloader does not fetch all 30 member files.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

try:
    from eccodes import codes_grib_find_nearest, codes_grib_new_from_file, codes_get, codes_get_values, codes_release
except ImportError as exc:  # pragma: no cover - exercised by an installation check, not unit tests
    raise SystemExit("install GRIB decoding dependencies with: ml/.venv/bin/pip install eccodes") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TABLE = REPO_ROOT / "data/processed/avalanche_nwac_observed_proxy.parquet"
DEFAULT_STATIC = REPO_ROOT / "data/processed/static/static_cells.parquet"
DEFAULT_OUT = REPO_ROOT / "data/processed/avalanche_noaa_gefs_forecasts.parquet"
DEFAULT_CACHE = REPO_ROOT / "data/raw/avalanche/noaa_gefs"

GEFS_BASE = "https://noaa-gefs-pds.s3.amazonaws.com"
SOURCE_URL = "https://registry.opendata.aws/noaa-gefs/"
LEADS = tuple(range(6, 79, 6))
OUTPUT_LEADS = tuple(range(12, 79, 6))
OPTIONAL_VARIABLES = ("apcp", "weasd", "tmp2m", "ugrd10m", "vgrd10m")
DEFAULT_VARIABLES = ("apcp",)
SPREAD_VARIABLES = frozenset({"apcp", "weasd"})
INDEX_RE = re.compile(r"^(?P<record>\d+):(?P<offset>\d+):(?P<descriptor>.*)$")


@dataclass(frozen=True)
class TargetCell:
    cell_id: str
    latitude: float
    longitude: float


class Downloader:
    def __init__(self, cache_dir: Path, timeout: int = 120, retries: int = 4, pause_seconds: float = 0.05) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.retries = retries
        self.pause_seconds = pause_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"requests": 0, "cache_hits": 0, "bytes": 0}

    def fetch(self, url: str, destination: Path, byte_range: tuple[int, int] | None = None) -> bytes:
        if destination.is_file() and destination.stat().st_size > 0:
            self.stats["cache_hits"] += 1
            return destination.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else {}
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self.stats["requests"] += 1
                request = Request(url, headers=headers)
                with urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                if byte_range and len(payload) != byte_range[1] - byte_range[0] + 1:
                    raise IOError(f"short byte-range response for {url}: {len(payload)} bytes")
                destination.write_bytes(payload)
                self.stats["bytes"] += len(payload)
                if self.pause_seconds:
                    time.sleep(self.pause_seconds)
                return payload
            except (HTTPError, URLError, TimeoutError, OSError, IOError) as error:
                last_error = error
                if attempt + 1 < self.retries:
                    time.sleep(min(8.0, 2**attempt))
        raise RuntimeError(f"failed to download {url}: {last_error}")

    def head_length(self, url: str) -> int:
        request = Request(url, method="HEAD")
        with urlopen(request, timeout=self.timeout) as response:
            return int(response.headers["Content-Length"])


def _cycle_for(reference: pd.Timestamp, lag_hours: int) -> pd.Timestamp:
    available_at = reference - pd.Timedelta(hours=lag_hours)
    return available_at.floor("6h").tz_convert("UTC")


def _url(variant: str, cycle: pd.Timestamp, lead: int) -> str:
    date = cycle.strftime("%Y%m%d")
    hour = cycle.strftime("%H")
    member = "geavg" if variant == "mean" else "gespr"
    return f"{GEFS_BASE}/gefs.{date}/{hour}/atmos/pgrb2sp25/{member}.t{hour}z.pgrb2s.0p25.f{lead:03d}"


def _idx_url(variant: str, cycle: pd.Timestamp, lead: int) -> str:
    return _url(variant, cycle, lead) + ".idx"


def _descriptor_matches(descriptor: str, variable: str, lead: int) -> bool:
    if variable == "apcp":
        start = lead - 6
        return f":APCP:surface:{start}-{lead} hour acc fcst" in descriptor
    if variable == "weasd":
        return ":WEASD:surface:" in descriptor
    if variable == "tmp2m":
        return ":TMP:2 m above ground:" in descriptor
    if variable == "ugrd10m":
        return ":UGRD:10 m above ground:" in descriptor
    if variable == "vgrd10m":
        return ":VGRD:10 m above ground:" in descriptor
    raise ValueError(f"unsupported variable {variable}")


def _message_range(index_text: bytes, variable: str, lead: int, object_size: int | None = None) -> tuple[int, int]:
    records: list[tuple[int, str]] = []
    for raw_line in index_text.decode("utf-8", errors="replace").splitlines():
        match = INDEX_RE.match(raw_line.strip())
        if match:
            records.append((int(match.group("offset")), match.group("descriptor")))
    for position, (offset, descriptor) in enumerate(records):
        if not _descriptor_matches(descriptor, variable, lead):
            continue
        if position + 1 < len(records):
            end = records[position + 1][0] - 1
        elif object_size is not None:
            end = object_size - 1
        else:
            raise ValueError(f"target GRIB message is final record but object size is unknown: {variable} f{lead:03d}")
        return offset, end
    raise ValueError(f"GRIB message not found: variable={variable} lead={lead}")


def _decode_point(path: Path, latitude: float, longitude: float) -> float:
    # ecCodes' file reader requires a real file descriptor on macOS; decoding directly from the
    # cached byte-range file also avoids a second in-memory copy of each GRIB message.
    with path.open("rb") as stream:
        handle = codes_grib_new_from_file(stream)
        if handle is None:
            raise ValueError("byte-range did not contain a GRIB message")
        try:
            nearest = codes_grib_find_nearest(handle, latitude, longitude)
            if not nearest:
                raise ValueError("GRIB message has no nearest point")
            value = float(nearest[0]["value"])
            if not math.isfinite(value):
                return float("nan")
            return value
        finally:
            codes_release(handle)


def _decode_points(path: Path, cells: list[TargetCell]) -> dict[str, float]:
    """Decode one message once and sample every cell from its regular lat/lon grid."""
    with path.open("rb") as stream:
        handle = codes_grib_new_from_file(stream)
        if handle is None:
            raise ValueError(f"byte-range did not contain a GRIB message: {path}")
        try:
            try:
                ni = int(codes_get(handle, "Ni"))
                first_lat = float(codes_get(handle, "latitudeOfFirstGridPointInDegrees"))
                first_lon = float(codes_get(handle, "longitudeOfFirstGridPointInDegrees"))
                di = float(codes_get(handle, "iDirectionIncrementInDegrees"))
                dj = float(codes_get(handle, "jDirectionIncrementInDegrees"))
                i_negative = bool(int(codes_get(handle, "iScansNegatively")))
                j_positive = bool(int(codes_get(handle, "jScansPositively")))
                values = codes_get_values(handle)
            except Exception:
                return {cell.cell_id: _decode_point(path, cell.latitude, cell.longitude) for cell in cells}
            output: dict[str, float] = {}
            for cell in cells:
                longitude = cell.longitude % 360.0
                i = round((longitude - first_lon) / di) if not i_negative else round((first_lon - longitude) / di)
                latitude_delta = (cell.latitude - first_lat) / dj
                j = round(latitude_delta) if j_positive else round(-latitude_delta)
                i = max(0, min(ni - 1, i))
                j = max(0, min(int(len(values) / ni) - 1, j))
                output[cell.cell_id] = float(values[j * ni + i])
            return output
        finally:
            codes_release(handle)


def _target_cells(table: pd.DataFrame, static_path: Path | None) -> list[TargetCell]:
    if static_path is not None and static_path.is_file():
        static = pd.read_parquet(static_path)
        requested = table[["cell_id"]].drop_duplicates()
        merged = requested.merge(static[["cell_id", "latitude", "longitude"]], on="cell_id", how="left")
        merged = merged.dropna(subset=["latitude", "longitude"])
        if not merged.empty:
            return [TargetCell(str(row.cell_id), float(row.latitude), float(row.longitude)) for row in merged.itertuples()]
    fallback = table[["cell_id", "latitude", "longitude"]].drop_duplicates("cell_id")
    return [TargetCell(str(row.cell_id), float(row.latitude), float(row.longitude)) for row in fallback.itertuples()]


def _message(
    downloader: Downloader,
    cache_root: Path,
    cycle: pd.Timestamp,
    lead: int,
    variant: str,
    variable: str,
) -> Path:
    url = _url(variant, cycle, lead)
    stem = f"{variant}_f{lead:03d}_{variable}"
    index_path = cache_root / cycle.strftime("%Y%m%d%H") / f"{variant}_f{lead:03d}.idx"
    index = downloader.fetch(_idx_url(variant, cycle, lead), index_path)
    target_path = cache_root / cycle.strftime("%Y%m%d%H") / f"{stem}.grib2"
    if target_path.is_file() and target_path.stat().st_size > 0:
        return target_path
    # The target messages are not at the end of the file in the current GEFS layout.  HEAD is
    # only needed for a future layout where an indexed target becomes the last record.
    try:
        byte_range = _message_range(index, variable, lead)
    except ValueError as error:
        if "final record" not in str(error):
            raise
        byte_range = _message_range(index, variable, lead, downloader.head_length(url))
    downloader.fetch(url, target_path, byte_range)
    return target_path


def _decode_values(
    downloader: Downloader,
    cache_root: Path,
    cycle: pd.Timestamp,
    lead: int,
    variable: str,
    cells: list[TargetCell],
    workers: int = 1,
) -> dict[str, float]:
    paths = _download_cycle_messages(downloader, cache_root, cycle, (lead,), (variable,), workers)
    return _decode_values_from_paths(paths, lead, variable, cells)


def _download_cycle_messages(
    downloader: Downloader,
    cache_root: Path,
    cycle: pd.Timestamp,
    leads: tuple[int, ...],
    variables: tuple[str, ...],
    workers: int,
) -> dict[tuple[int, str, str], Path]:
    jobs: dict[Any, tuple[int, str, str]] = {}
    paths: dict[tuple[int, str, str], Path] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for lead in leads:
            for variable in variables:
                variants = ("mean", "spread") if variable in SPREAD_VARIABLES else ("mean",)
                for variant in variants:
                    future = executor.submit(_message, downloader, cache_root, cycle, lead, variant, variable)
                    jobs[future] = (lead, variant, variable)
        for future in as_completed(jobs):
            paths[jobs[future]] = future.result()
    return paths


def _decode_values_from_paths(
    paths: dict[tuple[int, str, str], Path],
    lead: int,
    variable: str,
    cells: list[TargetCell],
) -> dict[str, float]:
    values: dict[str, float] = {}
    variants = ("mean", "spread") if variable in SPREAD_VARIABLES else ("mean",)
    for variant in variants:
        payload = paths[(lead, variant, variable)]
        decoded_points = _decode_points(payload, cells)
        for cell in cells:
            value = decoded_points[cell.cell_id]
            if variable == "tmp2m":
                value -= 273.15
            elif variable in {"ugrd10m", "vgrd10m"}:
                value *= 3.6
            values[f"{variant}_{variable}_{cell.cell_id}"] = value
    return values


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def download_forecasts(
    table: pd.DataFrame,
    static_path: Path | None,
    out: Path,
    cache_dir: Path,
    lag_hours: int,
    max_references: int | None,
    timeout: int,
    workers: int,
    allow_missing: bool = False,
    variables: tuple[str, ...] = DEFAULT_VARIABLES,
) -> dict[str, Any]:
    required = {"reference_timestamp", "cell_id", "latitude", "longitude"}
    missing = sorted(required - set(table.columns))
    if missing:
        raise ValueError(f"training table missing columns: {missing}")
    table = table.copy()
    table["reference_timestamp"] = pd.to_datetime(table["reference_timestamp"], utc=True)
    references = sorted(table["reference_timestamp"].drop_duplicates())
    if max_references is not None:
        references = references[:max_references]
    cells = _target_cells(table.loc[table["reference_timestamp"].isin(references)], static_path)
    if not references or not cells:
        raise ValueError("no references or target cells available")

    downloader = Downloader(cache_dir, timeout=timeout)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for reference in references:
        cycle = _cycle_for(reference, lag_hours)
        previous: dict[str, dict[str, float]] = {cell.cell_id: {} for cell in cells}
        try:
            message_paths = _download_cycle_messages(downloader, cache_dir, cycle, LEADS, variables, workers)
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
            failures.append({"reference_timestamp": reference.isoformat(), "cycle": cycle.isoformat(), "lead": "cycle", "error": str(error)})
            continue
        for lead in LEADS:
            decoded: dict[str, float] = {}
            for variable in variables:
                decoded.update(_decode_values_from_paths(message_paths, lead, variable, cells))
            if lead not in OUTPUT_LEADS:
                for cell in cells:
                    previous[cell.cell_id] = decoded_for_cell(decoded, cell.cell_id)
                continue
            forecast_time = cycle + pd.Timedelta(hours=lead - 6)
            for cell in cells:
                current = decoded_for_cell(decoded, cell.cell_id)
                prior = previous[cell.cell_id]
                current_weasd = current.get("mean_weasd", float("nan"))
                prior_weasd = prior.get("mean_weasd", float("nan"))
                weasd_delta = max(0.0, current_weasd - prior_weasd) if prior and math.isfinite(current_weasd) and math.isfinite(prior_weasd) else float("nan")
                current_weasd_spread = current.get("spread_weasd", float("nan"))
                prior_weasd_spread = prior.get("spread_weasd", float("nan"))
                spread_delta = math.sqrt(max(0.0, current_weasd_spread**2 + prior_weasd_spread**2)) if prior and math.isfinite(current_weasd_spread) and math.isfinite(prior_weasd_spread) else float("nan")
                snow_cm = weasd_delta * 0.1 if math.isfinite(weasd_delta) else float("nan")
                snow_spread_cm = spread_delta * 0.1 if math.isfinite(spread_delta) else float("nan")
                rows.append({
                    "cell_id": cell.cell_id,
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "reference_timestamp": reference.isoformat(),
                    "forecast_initialization": cycle.isoformat(),
                    "forecast_timestamp": forecast_time.isoformat(),
                    "forecast_lead_hours": lead - 6,
                    "forecast_precipitation_mm": current.get("mean_apcp"),
                    "forecast_precipitation_spread_mm": current.get("spread_apcp"),
                    "forecast_snowfall_cm": snow_cm,
                    "forecast_snowfall_spread_cm": snow_spread_cm,
                    "forecast_temperature_c": current.get("mean_tmp2m"),
                    "forecast_wind_speed_kmh": math.hypot(current.get("mean_ugrd10m", float("nan")), current.get("mean_vgrd10m", float("nan"))),
                    "forecast_wind_gust_kmh": None,
                    "forecast_wind_direction_deg": (math.degrees(math.atan2(-current.get("mean_ugrd10m", 0.0), -current.get("mean_vgrd10m", 0.0))) % 360.0),
                    "forecast_snow_water_equivalent_mm": current.get("mean_weasd"),
                    "forecast_source": "NOAA_GEFS",
                    "forecast_resolution_deg": 0.25,
                    "forecast_snowfall_method": "WEASD_delta_10_to_1_proxy",
                })
                previous[cell.cell_id] = current
    if not rows:
        raise RuntimeError(f"no forecast rows were downloaded; failures={failures[:3]}")
    if failures and not allow_missing:
        raise RuntimeError(f"historical NOAA forecast backfill incomplete: {len(failures)} failed lead/reference groups; first={failures[:3]}")
    frame = pd.DataFrame(rows)
    # Add a reference-level ensemble snowfall summary from the GEFS mean/spread products.  The
    # summary is repeated on each lead row to keep the join simple and deterministic.
    summary = frame.groupby(["cell_id", "reference_timestamp"], as_index=False).agg(
        forecast_snowfall_ensemble_mean=("forecast_snowfall_cm", lambda values: values.sum(min_count=1)),
        forecast_snowfall_ensemble_spread=("forecast_snowfall_spread_cm", lambda values: (
            math.sqrt(sum(float(v) ** 2 for v in values if pd.notna(v)))
            if any(pd.notna(v) for v in values) else float("nan")
        )),
    )
    summary["forecast_snowfall_ensemble_p90"] = summary["forecast_snowfall_ensemble_mean"] + 1.2815515655 * summary["forecast_snowfall_ensemble_spread"]
    summary["forecast_snowfall_ensemble_p95"] = summary["forecast_snowfall_ensemble_mean"] + 1.6448536269 * summary["forecast_snowfall_ensemble_spread"]
    summary["forecast_exceedance_probability"] = summary.apply(
        lambda row: 1.0 - _normal_cdf((20.0 - row.forecast_snowfall_ensemble_mean) / max(row.forecast_snowfall_ensemble_spread, 1e-6)), axis=1
    )
    frame = frame.merge(summary, on=["cell_id", "reference_timestamp"], how="left")
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    manifest = {
        "source": SOURCE_URL,
        "bucket": "s3://noaa-gefs-pds",
        "model": "GEFS",
        "product": "pgrb2sp25/geavg + gespr",
        "variables": list(variables),
        "references_requested": len(references),
        "references_completed": int(frame["reference_timestamp"].nunique()),
        "target_cells": len(cells),
        "rows": len(frame),
        "failures": failures,
        "lag_hours": lag_hours,
        "output": str(out),
        "cache_dir": str(cache_dir),
        "download_stats": downloader.stats,
        "accessed_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (out.with_suffix(".manifest.json")).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def decoded_for_cell(decoded: dict[str, float], cell_id: str) -> dict[str, float]:
    suffix = f"_{cell_id}"
    return {key.removesuffix(suffix): value for key, value in decoded.items() if key.endswith(suffix)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--lag-hours", type=int, default=6)
    parser.add_argument("--max-references", type=int)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--workers", type=int, default=8, help="Concurrent NOAA object requests per lead")
    parser.add_argument("--allow-missing", action="store_true", help="Write a partial table instead of failing on any missing lead/reference")
    parser.add_argument("--variables", default=",".join(DEFAULT_VARIABLES), help=f"Comma-separated GEFS variables (available: {','.join(OPTIONAL_VARIABLES)}; default: apcp)")
    args = parser.parse_args()
    table = pd.read_parquet(args.table)
    variables = tuple(item.strip() for item in args.variables.split(",") if item.strip())
    invalid = sorted(set(variables) - set(OPTIONAL_VARIABLES))
    if invalid:
        parser.error(f"unsupported --variables: {invalid}")
    manifest = download_forecasts(table, args.static, args.out, args.cache_dir, args.lag_hours, args.max_references, args.timeout, args.workers, args.allow_missing, variables)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
