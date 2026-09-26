#!/usr/bin/env python3
"""Download local satellite/aerial snapshots for the catalog mountains.

The source is the public Esri World Imagery export service.  Each output is a georeferenced
by-metadata JPEG snapshot centered on one catalog mountain; the image itself is a 512x512
visual crop, not a model feature raster.  Raw images belong in data/raw/ and are gitignored.

Run from the repository root:

  python ml/scripts/download_satellite_images.py
  python ml/scripts/download_satellite_images.py --slugs mount-everest,k2
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "data" / "seed" / "mountains_test.json"
DEFAULT_OUT = REPO_ROOT / "data" / "raw" / "satellite"
DEFAULT_CSV = REPO_ROOT / "data" / "seed" / "mountain_satellite_images.csv"
ESRI_EXPORT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"


def bbox_for(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return a longitude/latitude bbox with approximately radius_km around the center."""
    lat_delta = radius_km / 111.32
    lon_delta = radius_km / (111.32 * max(0.1, abs(math.cos(math.radians(lat)))))
    return lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta


def source_url(bbox: tuple[float, float, float, float], size: int) -> str:
    params = {
        "bbox": ",".join(f"{v:.7f}" for v in bbox),
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{size},{size}",
        "format": "jpg",
        "f": "image",
        "transparent": "false",
        "compressionQuality": "90",
    }
    return f"{ESRI_EXPORT}?{urlencode(params)}"


def download(url: str, path: Path, timeout: int = 90, retries: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "TerraSense/1.0 satellite snapshot downloader"})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS source
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
            if not body.startswith(b"\xff\xd8\xff") or "image" not in content_type.lower():
                raise RuntimeError(f"unexpected response: content_type={content_type!r}, bytes={len(body)}")
            partial.write_bytes(body)
            partial.replace(path)
            return
        except Exception as exc:  # retry transient service/network errors
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed for {url}: {last_error}")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--radius-km", type=float, default=5.0)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--slugs", help="comma-separated subset of mountain slugs")
    parser.add_argument("--force", action="store_true", help="redownload existing images")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    mountains = json.loads(args.registry.read_text(encoding="utf-8"))
    wanted = set(args.slugs.split(",")) if args.slugs else None
    if wanted:
        unknown = wanted - {m["slug"] for m in mountains}
        if unknown:
            raise SystemExit(f"unknown mountain slug(s): {', '.join(sorted(unknown))}")

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for mountain in mountains:
        if wanted and mountain["slug"] not in wanted:
            continue
        bbox = bbox_for(float(mountain["lat"]), float(mountain["lon"]), args.radius_km)
        path = args.out / f"{mountain['slug']}.jpg"
        url = source_url(bbox, args.size)
        status = "downloaded"
        error = ""
        if path.exists() and not args.force:
            status = "cached"
        else:
            try:
                print(f"downloading {mountain['name']} -> {path.relative_to(REPO_ROOT)}", flush=True)
                download(url, path)
            except Exception as exc:
                status = "error"
                error = str(exc)
                print(f"ERROR {mountain['name']}: {error}", file=sys.stderr, flush=True)
        rows.append({
            "mountain_name": mountain["name"],
            "mountain_slug": mountain["slug"],
            "satellite_image_file_extension": "jpg",
            "satellite_image_file_path": str(path.relative_to(REPO_ROOT)),
            "download_status": status,
            "source": "Esri World Imagery",
            "source_url": url,
            "bbox_west": round(bbox[0], 7),
            "bbox_south": round(bbox[1], 7),
            "bbox_east": round(bbox[2], 7),
            "bbox_north": round(bbox[3], 7),
            "image_size_px": args.size,
            "error": error,
        })

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["mountain_name", "mountain_slug", "satellite_image_file_extension"]
    with args.csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    ok = sum(row["download_status"] in {"downloaded", "cached"} for row in rows)
    print(f"wrote {args.csv.relative_to(REPO_ROOT)}: {ok}/{len(rows)} images available")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
