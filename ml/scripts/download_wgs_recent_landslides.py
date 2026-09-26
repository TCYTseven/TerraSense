#!/usr/bin/env python3
"""Cache Washington Geological Survey's dated recent-landslide layer.

This is an independent external-label audit source for the landslide stack.  The layer is not a
rainfall-triggered inventory: most records have only an observation year and no trigger.  The
downloader therefore preserves the complete GeoJSON and writes exact-date records separately,
but never promotes them to rainfall-triggered 72-hour labels automatically.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY_URL = "https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/1/query"
SOURCE_URL = "https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/1"


def fetch_layer(*, timeout: int = 120) -> dict[str, Any]:
    query = urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "geojson"})
    request = Request(f"{QUERY_URL}?{query}", headers={"Accept": "application/geo+json", "User-Agent": "TerraSense/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official HTTPS URL
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("WGS recent-landslides response is not a GeoJSON FeatureCollection")
    return payload


def dated_audit_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        date_move = props.get("DATE_MOVE")
        if date_move is None or len(coords) < 2:
            continue
        rows.append({
            "event_id": f"wgs_recent:{props.get('RECENT_LS_ID') or props.get('OBJECTID')}",
            "event_timestamp": datetime.fromtimestamp(float(date_move) / 1000, tz=UTC).isoformat(),
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
            "trigger": None,
            "confidence": props.get("CONFIDENCE"),
            "location_accuracy": props.get("LOCATION_ACCURACY"),
            "field_verified": props.get("FIELD_VERIFIED"),
            "source": "Washington Geological Survey Recent Landslides",
            "source_url": SOURCE_URL,
            "rainfall_trigger_status": "unknown_audit_only",
        })
    return rows


def download(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = fetch_layer()
    raw_path = out_dir / "recent_landslides.geojson"
    raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    rows = dated_audit_rows(payload)
    (out_dir / "dated_audit_rows.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source": "Washington Geological Survey Recent Landslides",
        "source_url": SOURCE_URL,
        "query_url": QUERY_URL,
        "accessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "records": len(payload["features"]),
        "exact_date_records": len(rows),
        "rainfall_trigger_status": "unknown_for_source_layer",
        "training_status": "audit_only",
        "limitation": "DATE_MOVE is an observed/mapped date and the layer does not establish a rainfall trigger; no rows are promoted to 72-hour rainfall labels.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data/raw/landslide/washington_wgs")
    args = parser.parse_args()
    print(json.dumps(download(args.out_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
