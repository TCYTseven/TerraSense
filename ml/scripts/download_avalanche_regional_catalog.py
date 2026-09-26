#!/usr/bin/env python3
"""Cache official Avalanche.org public observations for a geographic holdout corpus.

This is an acquisition/audit step, not an automatic training step.  Public observations are
reporting-biased and field reports with ``avalanches_observed=false`` are coverage-backed controls,
not proof that no avalanche occurred elsewhere in the cell.  The raw pages stay gitignored and a
manifest preserves the exact query and counts.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://api.avalanche.org/obs/v1/public"
DEFAULT_BBOX = "-125,42,-116,49.1"  # Washington/Oregon Cascades and adjacent NWAC terrain


def fetch_json(url: str, retries: int = 3) -> dict:
    request = Request(url, headers={"Accept": "application/json", "Origin": "https://nwac.us", "Referer": "https://nwac.us/"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed HTTPS API host
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # pragma: no cover - network dependent
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last_error}")


def page_url(resource: str, *, start_date: str, end_date: str, bbox: str, page: int, page_size: int) -> str:
    query = urlencode({
        "date[gte]": start_date,
        "date[lte]": end_date,
        "page": page,
        "page_size": page_size,
        "sort_by": "date",
        "sort_order": "desc",
        "bbox": bbox,
    })
    return f"{BASE_URL}/{resource}/list/?{query}"


def download_resource(resource: str, *, start_date: str, end_date: str, bbox: str, out_dir: Path, workers: int) -> dict:
    page_size = 100
    first_url = page_url(resource, start_date=start_date, end_date=end_date, bbox=bbox, page=1, page_size=page_size)
    first = fetch_json(first_url)
    total_pages = int(first.get("pages") or 1)
    pages: dict[int, dict] = {1: first}
    urls = {page: page_url(resource, start_date=start_date, end_date=end_date, bbox=bbox, page=page, page_size=page_size) for page in range(1, total_pages + 1)}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_json, url): page for page, url in urls.items() if page != 1}
        for future in as_completed(futures):
            pages[futures[future]] = future.result()
    name = "avalanche_observations" if resource == "avalanche_observation" else "field_observations"
    out_dir.mkdir(parents=True, exist_ok=True)
    record_count = 0
    filtered_count = 0
    excluded_count = 0
    for page in range(1, total_pages + 1):
        payload = pages[page]
        records = payload.get("results", [])
        record_count += len(records)
        in_range = []
        for record in records:
            value = str(record.get("date") or record.get("start_date") or "")[:10]
            if start_date <= value <= end_date:
                in_range.append(record)
            else:
                excluded_count += 1
        filtered_count += len(in_range)
        filtered_payload = {**payload, "results": in_range, "total": filtered_count}
        (out_dir / f"{name}_page_{page:04d}.json").write_text(json.dumps(filtered_payload, indent=2) + "\n", encoding="utf-8")
    return {"resource": resource, "pages": total_pages, "records_returned": record_count, "records_in_query_range": filtered_count, "records_excluded_by_date": excluded_count, "urls": list(urls.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2023-10-25")
    parser.add_argument("--end-date", default="2026-07-20")
    parser.add_argument("--bbox", default=DEFAULT_BBOX)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data/raw/avalanche/regional_nwac")
    args = parser.parse_args()
    results = [
        download_resource("avalanche_observation", start_date=args.start_date, end_date=args.end_date, bbox=args.bbox, out_dir=args.out_dir, workers=args.workers),
        download_resource("observation", start_date=args.start_date, end_date=args.end_date, bbox=args.bbox, out_dir=args.out_dir, workers=args.workers),
    ]
    manifest = {
        "source": "National Avalanche Center / Avalanche.org public observations API",
        "source_url": "https://github.com/NationalAvalancheCenter/Avalanche.org-Public-API-Docs",
        "accessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "query": {"start_date": args.start_date, "end_date": args.end_date, "bbox": args.bbox, "page_size": 100},
        "resources": results,
        "training_status": "acquired_for_audit_only",
        "limitations": [
            "public observations are reporting-biased and not a complete inventory",
            "field reports with avalanches_observed=false are coverage-backed controls, not universal negatives",
            "terrain/weather feature extraction and spatially external validation are required before training",
        ],
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
