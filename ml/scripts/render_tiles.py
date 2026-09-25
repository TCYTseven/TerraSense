#!/usr/bin/env python3
"""Render a 0-1 raster to XYZ map tiles (implementation steps 13 and 18).

Writes backend/tiles/<layer>/{z}/{x}/{y}.png in Web Mercator (EPSG:3857), plus metadata.json,
where the API serves them at /tiles and describes them at GET /mountains/{slug}/layers/{layer}.

Run from the repo root:
  python ml/scripts/render_tiles.py                         # susceptibility, z10-z14
  python ml/scripts/render_tiles.py --layer probability --raster PATH --zooms 10-14
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# The tiler lives in the API package so the live probability layer renders the same way.
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.tiles import TILES_DIR, render_xyz  # noqa: E402

DEFAULT_RASTER = REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"


def zoom_range(text: str) -> range:
    """'10-14' to range(10, 15)."""
    low, _, high = text.partition("-")
    return range(int(low), int(high or low) + 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a 0-1 raster to XYZ PNG tiles.")
    parser.add_argument("--layer", default="susceptibility", help="layer name, and the tile folder")
    parser.add_argument("--raster", type=Path, default=DEFAULT_RASTER, help="single-band 0-1 GeoTIFF")
    parser.add_argument("--zooms", type=zoom_range, default=range(10, 15), help="zoom range, e.g. 10-14")
    args = parser.parse_args()

    if not args.raster.exists():
        raise SystemExit(f"{args.raster} is missing. Run ml/scripts/train_susceptibility.py first.")
    metadata = render_xyz(args.raster, args.layer, args.zooms)
    out = (TILES_DIR / args.layer).relative_to(REPO_ROOT)
    print(f"wrote {metadata['tile_count']} tiles, z{metadata['minzoom']}-z{metadata['maxzoom']}, "
          f"to {out}/{{z}}/{{x}}/{{y}}.png (method: {metadata['method']}, version {metadata['version']})")


if __name__ == "__main__":
    main()
