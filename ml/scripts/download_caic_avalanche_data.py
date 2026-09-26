#!/usr/bin/env python3
"""Cache historical avalanche observations from the official CAIC public site API.

CAIC's Avalanche Explorer is a useful independent label source for geographic transfer, but its
public API is not a promise of complete areal coverage.  This downloader keeps the raw payloads,
normalizes the fields needed for the canonical event builder, and writes a manifest with the exact
query.  It does *not* create negatives and it does not join records to model features; that must
be done with an as-of weather/forecast and terrain pipeline before training.

The endpoint is a read-only API behind the official Colorado Avalanche Information Center site.
Its schema is not versioned in a public contract, so failures are explicit and raw pages are
retained for audit rather than silently reshaped.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
API_BASE = "https://api.avalanche.state.co.us/api/v2"
SOURCE_URL = "https://avalanche.state.co.us/observations"
DEFAULT_START_DATE = "2013-10-01"


def fetch_page(url: str, *, retries: int = 4, timeout: int = 120) -> list[dict[str, Any]]:
    """Fetch one page, accepting CAIC's list response and rejecting malformed payloads."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TerraSense/1.0 (research data acquisition)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise ValueError("CAIC response is not a list of objects")
            return payload
        except Exception as error:  # pragma: no cover - network failures are environment-dependent
            last_error = error
            if attempt + 1 < retries:
                time.sleep(min(8, 2**attempt))
    raise RuntimeError(f"CAIC download failed after {retries} attempts: {url}: {last_error}")


def query_url(*, start_date: str, end_date: str, page: int, per_page: int, resource: str = "avalanche_observations", no_avalanche_only: bool = False) -> str:
    query = urlencode(
        [
            ("page", page),
            ("per", per_page),
            ("r[observed_at_gteq]", f"{start_date}T00:00:00.000Z"),
            ("r[observed_at_lteq]", f"{end_date}T23:59:59.999Z"),
            ("r[sorts][]", "observed_at desc"),
        ]
    )
    suffix = "&r%5Bsaw_avalanche_eq%5D=false" if no_avalanche_only else ""
    return f"{API_BASE}/{resource}?{query}{suffix}"


def normalize_event(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map a CAIC observation to the shared event shape without inventing missing values."""
    observed_at = row.get("observed_at")
    latitude, longitude = row.get("latitude"), row.get("longitude")
    if not observed_at or latitude is None or longitude is None:
        return None
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    return {
        "event_id": str(row.get("id") or ""),
        "event_timestamp": str(observed_at),
        "latitude": latitude,
        "longitude": longitude,
        "event_type": row.get("type_code"),
        "problem_type": row.get("problem_type"),
        "trigger": row.get("primary_trigger"),
        "secondary_trigger": row.get("secondary_trigger"),
        "relative_size": row.get("relative_size"),
        "destructive_size": row.get("destructive_size"),
        "aspect": row.get("aspect"),
        "elevation_feet": row.get("elevation_feet"),
        "slope_angle_average": row.get("angle_average"),
        "water_year": row.get("water_year"),
        "verified": row.get("observation_report", {}).get("status") == "approved",
        "source": "CAIC",
        "source_url": SOURCE_URL,
    }


def normalize_control(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a field report with an explicit no-avalanche observation.

    CAIC reports do not always put coordinates on the report itself.  Prefer a nested snowpack
    or weather observation coordinate and discard reports without one rather than guessing a
    point from a zone polygon.
    """
    # A missing count is not proof that the reporter observed no avalanche.  Treat only
    # the explicit zero values as coverage-backed controls.
    if row.get("avalanche_observations_count") not in (0, "0"):
        return None
    observations = [*(row.get("snowpack_observations") or []), *(row.get("weather_observations") or [])]
    point = next((item for item in observations if item.get("latitude") is not None and item.get("longitude") is not None), None)
    if point is None or row.get("observed_at") is None:
        return None
    return {
        "control_id": str(row.get("id") or ""),
        "event_timestamp": str(row["observed_at"]),
        "latitude": float(point["latitude"]),
        "longitude": float(point["longitude"]),
        "label": 0,
        "label_confidence": "coverage_backed_no_avalanche_report",
        "source": "CAIC",
        "source_url": SOURCE_URL,
        "backcountry_zone": (row.get("backcountry_zone") or {}).get("title"),
    }


def download(
    *,
    start_date: str,
    end_date: str,
    out_dir: Path,
    per_page: int = 250,
    max_pages: int = 200,
    sleep_seconds: float = 0.05,
    include_controls: bool = False,
) -> dict[str, Any]:
    """Download all pages in the bounded interval, stopping only at an empty/short page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    page_urls: list[str] = []
    raw_pages = 0
    previous_manifest_path = out_dir / "manifest.json"
    previous_events_path = out_dir / "events.json"
    previous_manifest: dict[str, Any] = {}
    if previous_manifest_path.is_file() and previous_events_path.is_file():
        try:
            previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous_manifest = {}
    previous_query = previous_manifest.get("query", {})
    reuse_events = (
        previous_query.get("start_date") == start_date
        and previous_query.get("end_date") == end_date
        and previous_query.get("per_page") == per_page
    )
    if reuse_events:
        normalized = json.loads(previous_events_path.read_text(encoding="utf-8"))
        raw_pages = int(previous_manifest.get("pages", 0))
        records_count = int(previous_manifest.get("records", len(normalized)))
        page_urls = list(previous_manifest.get("page_urls", []))
    else:
        for page in range(1, max_pages + 1):
            url = query_url(start_date=start_date, end_date=end_date, page=page, per_page=per_page)
            rows = fetch_page(url)
            raw_pages += 1
            page_urls.append(url)
            (out_dir / f"avalanche_observations_page_{page:04d}.json").write_text(
                json.dumps({"results": rows}, indent=2) + "\n", encoding="utf-8"
            )
            records.extend(rows)
            if not rows or len(rows) < per_page:
                break
        else:
            raise RuntimeError(f"CAIC pagination exceeded --max-pages={max_pages}; refusing partial data")
        normalized = [event for row in records if (event := normalize_event(row)) is not None]
        records_count = len(records)
        (out_dir / "events.json").write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    controls: list[dict[str, Any]] = []
    control_pages = 0
    control_urls: list[str] = []
    if include_controls:
        for page in range(1, max_pages + 1):
            url = query_url(start_date=start_date, end_date=end_date, page=page, per_page=per_page, resource="observation_reports", no_avalanche_only=True)
            rows = fetch_page(url)
            control_pages += 1
            control_urls.append(url)
            (out_dir / f"observation_reports_page_{page:04d}.json").write_text(
                json.dumps({"results": rows}, indent=2) + "\n", encoding="utf-8"
            )
            controls.extend(control for row in rows if (control := normalize_control(row)) is not None)
            if not rows or len(rows) < per_page:
                break
        else:
            raise RuntimeError(f"CAIC observation-report pagination exceeded --max-pages={max_pages}; refusing partial data")
        (out_dir / "controls.json").write_text(json.dumps(controls, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "source": "Colorado Avalanche Information Center public avalanche observations API",
        "source_url": SOURCE_URL,
        "api_base": API_BASE,
        "accessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "query": {"start_date": start_date, "end_date": end_date, "per_page": per_page},
        "pages": raw_pages,
        "records": records_count,
        "normalized_events": len(normalized),
        "page_urls": page_urls,
        "controls": {"enabled": include_controls, "pages": control_pages, "records": len(controls), "page_urls": control_urls},
        "training_status": "acquired_for_audit_only",
        "limitations": [
            "CAIC observations are reporting-biased and do not define complete no-event coverage",
            "the public API is not a versioned data contract",
            "records need spatial terrain and leakage-safe as-of weather/forecast joins before training",
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--per-page", type=int, default=250)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--include-controls", action="store_true", help="also cache CAIC field reports with zero avalanche observations as coverage-backed controls")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data/raw/avalanche/caic")
    args = parser.parse_args()
    print(json.dumps(download(start_date=args.start_date, end_date=args.end_date, out_dir=args.out_dir, per_page=args.per_page, max_pages=args.max_pages, include_controls=args.include_controls), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
