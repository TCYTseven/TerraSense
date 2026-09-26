#!/usr/bin/env python3
"""Render a 0-1 raster to XYZ map tiles (implementation steps 13, 18, and 32).

Writes backend/tiles/<layer>/{z}/{x}/{y}.png in Web Mercator (EPSG:3857), plus metadata.json,
where the API serves them at /tiles and describes them at GET /mountains/{slug}/layers/{layer}.
Packs from ml/scripts/mountain_packs.py render under backend/tiles/<slug>/<layer>/.

Run from the repo root:
  python ml/scripts/render_tiles.py                         # Rainier susceptibility, z10-z14
  python ml/scripts/render_tiles.py --mountain mount-fuji   # a pack's susceptibility index
  python ml/scripts/render_tiles.py --layer probability --raster PATH --zooms 10-14
"""

import argparse
import sys
from pathlib import Path

import mountain_packs as mp

REPO_ROOT = Path(__file__).resolve().parents[2]
# The tiler lives in the API package so the live probability layer renders the same way.
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.tiles import render_xyz, slug_tiles_dir  # noqa: E402


def zoom_range(text: str) -> range:
    """'10-14' to range(10, 15)."""
    low, _, high = text.partition("-")
    return range(int(low), int(high or low) + 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a 0-1 raster to XYZ PNG tiles.")
    parser.add_argument("--mountain", default=mp.RAINIER_SLUG,
                        help=f"pack slug from mountain_packs.py (default: {mp.RAINIER_SLUG})")
    parser.add_argument("--layer", default="susceptibility", help="layer name, and the tile folder")
    parser.add_argument("--raster", type=Path, default=None,
                        help="single-band 0-1 GeoTIFF (default: the pack's susceptibility)")
    parser.add_argument("--zooms", type=zoom_range, default=range(10, 15), help="zoom range, e.g. 10-14")
    args = parser.parse_args()
    pack, paths = mp.get(args.mountain), mp.paths(args.mountain)
    raster = args.raster or paths.artifacts / "susceptibility.tif"

    if not raster.exists():
        raise SystemExit(f"{raster} is missing. Run ml/scripts/train_susceptibility.py "
                         f"--mountain {pack.slug} first.")
    tiles_dir = slug_tiles_dir(pack.slug)
    metadata = render_xyz(raster, args.layer, args.zooms, bbox=pack.bbox, tiles_dir=tiles_dir)
    out = (tiles_dir / args.layer).relative_to(REPO_ROOT)
    print(f"wrote {metadata['tile_count']} tiles, z{metadata['minzoom']}-z{metadata['maxzoom']}, "
          f"to {out}/{{z}}/{{x}}/{{y}}.png (method: {metadata['method']}, version {metadata['version']})")


if __name__ == "__main__":
    main()
