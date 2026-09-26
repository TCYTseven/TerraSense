#!/usr/bin/env python3
"""Cache one explicitly supplied risk-pipeline source and update its provenance manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from risk_sources import MANIFEST_PATH, SOURCE_SPECS, SourceRecord, download_cached, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=sorted(SOURCE_SPECS))
    parser.add_argument("--url", required=True, help="explicit product URL or signed download URL")
    parser.add_argument("--out", type=Path, required=True, help="cache path under data/raw or another ignored directory")
    parser.add_argument("--sha256", help="optional expected checksum")
    args = parser.parse_args()
    record = download_cached(args.url, args.out, expected_sha256=args.sha256)
    record = SourceRecord(
        source_id=args.source,
        path=record.path,
        sha256=record.sha256,
        bytes=record.bytes,
        downloaded_at=record.downloaded_at,
        source_url=record.source_url,
        source_version=record.source_version,
        temporal_start=record.temporal_start,
        temporal_end=record.temporal_end,
        spatial_resolution=record.spatial_resolution,
        quality_flags=record.quality_flags,
    )
    records = []
    if MANIFEST_PATH.exists():
        import json

        records = [SourceRecord(**item) for item in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("sources", [])]
        records = [item for item in records if item.source_id != args.source]
    write_manifest([*records, record])
    print(f"cached {args.source}: {record.path} ({record.bytes} bytes, sha256={record.sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
