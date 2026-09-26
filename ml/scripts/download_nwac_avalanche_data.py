#!/usr/bin/env python3
"""Download Rainier avalanche observations and historical weather inputs.

The NWAC/National Avalanche Center public API is used for occurrence and field-observation
records.  Open-Meteo archive data is retained only as a development/retrospective weather
source; it is not a substitute for archived NOAA forecasts when training the operational
forecast-conditioned model.

Raw outputs are intentionally written below ``data/raw/avalanche`` (gitignored).  A manifest
records URLs, query parameters, access time, and byte counts so a run is reproducible.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BBOX = "-121.93,46.76,-121.54,46.96"
NWAC_BASE = "https://api.avalanche.org/obs/v1/public"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def fetch_json(url: str, *, headers: dict[str, str] | None = None, retries: int = 3) -> dict:
    request = Request(url, headers=headers or {"Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed HTTPS URLs above
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # pragma: no cover - network failures are environment-dependent
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None, retries: int = 3) -> bytes:
    request = Request(url, headers=headers or {})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=180) as response:  # noqa: S310 - fixed HTTPS URLs above
                return response.read()
        except Exception as error:  # pragma: no cover - network failures are environment-dependent
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def nwac_page(resource: str, *, start_date: str, end_date: str, bbox: str, page: int) -> tuple[str, dict]:
    query = urlencode(
        {
            "date[gte]": start_date,
            "date[lte]": end_date,
            "page": page,
            "page_size": 100,
            "sort_by": "date",
            "sort_order": "desc",
            "bbox": bbox,
        }
    )
    url = f"{NWAC_BASE}/{resource}/list/?{query}"
    return url, fetch_json(url, headers={"Accept": "application/json", "Origin": "https://nwac.us", "Referer": "https://nwac.us/"})


def download_nwac(resource: str, *, start_date: str, end_date: str, bbox: str, out_dir: Path) -> list[dict]:
    first_url, first = nwac_page(resource, start_date=start_date, end_date=end_date, bbox=bbox, page=1)
    total_pages = int(first.get("pages") or 1)
    pages = [first]
    urls = [first_url]
    for page in range(2, total_pages + 1):
        url, payload = nwac_page(resource, start_date=start_date, end_date=end_date, bbox=bbox, page=page)
        urls.append(url)
        pages.append(payload)
    for index, payload in enumerate(pages, start=1):
        name = "avalanche_observations" if resource == "avalanche_observation" else "field_observations"
        (out_dir / f"{name}_page_{index}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return [{"source": "NWAC/NAC public observations API", "url": url, "rows": len(payload.get("results", []))} for url, payload in zip(urls, pages, strict=False)]


def download_weather(*, latitude: float, longitude: float, start_date: str, end_date: str, out_dir: Path) -> dict:
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(("precipitation", "snowfall", "snow_depth", "temperature_2m", "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m")),
            "timezone": "UTC",
        }
    )
    url = f"{OPEN_METEO_ARCHIVE}?{query}"
    payload = fetch_json(url)
    path = out_dir / f"openmeteo_{latitude:.4f}_{longitude:.4f}_{start_date}_{end_date}.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return {"source": "Open-Meteo archive (ERA5-Land/forecast-model blend)", "url": url, "path": str(path), "rows": len(payload.get("hourly", {}).get("time", []))}


def download_snotel(*, start_date: str, end_date: str, out_dir: Path) -> dict:
    # NRCS Report Generator is the public export path for Paradise SNOTEL (679:WA:SNTL).
    path_spec = "679%3AWA%3ASNTL/" + f"{start_date}%2C{end_date}/WTEQ%3A%3Avalue%2CSNWD%3A%3Avalue%2CPREC%3A%3Avalue%2CTOBS%3A%3Avalue"
    url = f"https://wcc.sc.egov.usda.gov/reportGenerator/view/customSingleStationReport/hourly/{path_spec}?fitToScreen=false&sortBy=0%3A1"
    payload = fetch_bytes(url, headers={"Accept": "text/html", "User-Agent": "TerraSense/1.0"})
    path = out_dir / f"paradise_679_{start_date}_{end_date}.html"
    path.write_bytes(payload)
    return {"source": "NRCS AWDB / Paradise SNOTEL station 679", "url": url, "path": str(path), "bytes": len(payload)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2023-10-25")
    parser.add_argument("--end-date", default="2026-07-20")
    parser.add_argument("--bbox", default=DEFAULT_BBOX)
    parser.add_argument("--weather-latitude", type=float, default=46.85)
    parser.add_argument("--weather-longitude", type=float, default=-121.75)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data/raw/avalanche")
    args = parser.parse_args()
    nwac_dir = args.out_dir / "nwac"
    weather_dir = args.out_dir / "weather"
    nwac_dir.mkdir(parents=True, exist_ok=True)
    weather_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "accessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bbox": args.bbox,
        "nwac": download_nwac("avalanche_observation", start_date=args.start_date, end_date=args.end_date, bbox=args.bbox, out_dir=nwac_dir)
        + download_nwac("observation", start_date=args.start_date, end_date=args.end_date, bbox=args.bbox, out_dir=nwac_dir),
        "weather": download_weather(latitude=args.weather_latitude, longitude=args.weather_longitude, start_date=args.start_date, end_date=args.end_date, out_dir=weather_dir),
        "snotel": download_snotel(start_date=args.start_date, end_date=args.end_date, out_dir=args.out_dir / "snotel"),
    }
    manifest["notes"] = [
        "NWAC field observations are used as a coverage signal, not proof of complete areal absence.",
        "Historical Open-Meteo weather is observed/reanalysis-style retrospective input. Archived NOAA forecast runs are still required for operational forecast-conditioned training.",
    ]
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
