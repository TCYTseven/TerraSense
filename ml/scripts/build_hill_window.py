#!/usr/bin/env python3
"""Score Turtle Mountain with the existing landslide model on its own terrain window.

Downloads a Copernicus DEM and WorldCover clip for the shared hill box, builds the
booster's feature bands, applies the trained LightGBM and its isotonic calibration,
runs Model B with rain at the summit, and renders XYZ tiles. It does not retrain,
does not register a step 32 pack, and does not replace Rainier's rasters.

Run from the repo root:
  python ml/scripts/build_hill_window.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.hills import (  # noqa: E402
    HILL_METHOD,
    TURTLE_BBOX,
    TURTLE_SLUG,
    hill_probability_path,
    hill_stack_path,
    hill_susceptibility_path,
    hills,
)
from app.ml.model_b import run as run_model_b  # noqa: E402
from app.ml.probability import ProbabilityMap, write as write_probability  # noqa: E402
from app.ml.tiles import render_xyz, slug_tiles_dir  # noqa: E402
from app.weather import get_hourly_rain  # noqa: E402
from apply_susceptibility_map import ARTIFACTS_DIR, load_fitted  # noqa: E402
from build_features import utm_grid  # noqa: E402
from build_regional_features import FEATURES, build_stack, write_stack  # noqa: E402
from download_region import dem_tiles, fetch_mosaic, worldcover_tiles  # noqa: E402
from train_regional_susceptibility import MODEL_FEATURES, predict_map, write_map  # noqa: E402

# Same margin the regional download uses, so relief and flow at the box edge see real ground.
DOWNLOAD_MARGIN_DEG = 0.05
RAINIER_SUSCEPTIBILITY = ARTIFACTS_DIR / "susceptibility.tif"
RAINIER_PROBABILITY = ARTIFACTS_DIR / "probability.tif"


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def utm_crs(lat: float, lon: float) -> str:
    zone = min(60, max(1, int((lon + 180) // 6) + 1))
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def download_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    return (west - DOWNLOAD_MARGIN_DEG, south - DOWNLOAD_MARGIN_DEG,
            east + DOWNLOAD_MARGIN_DEG, north + DOWNLOAD_MARGIN_DEG)


def raw_dir(slug: str) -> Path:
    return REPO_ROOT / "data" / "raw" / "hills" / slug


def fetch(path: Path, urls: list[str], bbox, dtype: str, nodata, predictor: int, force: bool) -> None:
    if path.is_file() and not force:
        print(f"  {rel(path)} exists, skipping (use --force)")
        return
    print(f"  reading {len(urls)} tile(s):")
    for url in urls:
        print(f"    {url}")
    fetch_mosaic(urls, path, bbox, dtype, nodata, predictor)


def require_bands(stack: np.ndarray) -> None:
    for index, name in enumerate(FEATURES):
        if not np.isfinite(stack[index]).any():
            raise SystemExit(f"{name} could not be computed; stopping")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and score the Turtle Mountain terrain window.")
    parser.add_argument("--force", action="store_true", help="download the DEM and land cover again")
    args = parser.parse_args()

    row = next((item for item in hills() if item["slug"] == TURTLE_SLUG), None)
    if row is None:
        raise SystemExit(f"{TURTLE_SLUG} is not in data/seed/hills.json")
    lat, lon = float(row["lat"]), float(row["lon"])
    crs = utm_crs(lat, lon)
    box = download_bbox(TURTLE_BBOX)
    dem_path = raw_dir(TURTLE_SLUG) / "dem_cop30.tif"
    landcover_path = raw_dir(TURTLE_SLUG) / "landcover_worldcover2021.tif"
    stack_path = hill_stack_path(TURTLE_SLUG)
    susceptibility_path = hill_susceptibility_path(TURTLE_SLUG)
    probability_path = hill_probability_path(TURTLE_SLUG)
    for path in (susceptibility_path, probability_path):
        if path in (RAINIER_SUSCEPTIBILITY, RAINIER_PROBABILITY):
            raise SystemExit(f"refusing to write {rel(path)}: that file is Rainier's")

    print(f"hill {TURTLE_SLUG} bbox {list(TURTLE_BBOX)}, reading {box}, grid {crs}")
    fetch(dem_path, dem_tiles(box), box, "float32", -32767.0, 3, args.force)
    fetch(landcover_path, worldcover_tiles(box), box, "uint8", 0, 1, args.force)

    transform, width, height = utm_grid(box, crs)
    print(f"feature grid {width} x {height} at 30 m")
    stack = build_stack(transform, (height, width), dem_path=dem_path, landcover_path=landcover_path, grid_crs=crs)
    require_bands(stack)
    for index, name in enumerate(FEATURES):
        values = stack[index]
        print(f"  {name:<18} min {np.nanmin(values):10.2f}  median {np.nanmedian(values):10.2f}  max {np.nanmax(values):10.2f}")
    stack_path.parent.mkdir(parents=True, exist_ok=True)
    write_stack(stack_path, stack, transform, crs=crs)
    print(f"wrote {rel(stack_path)} ({stack_path.stat().st_size / 1e6:.1f} MB)")

    fitted = load_fitted(ARTIFACTS_DIR / "susceptibility_lgbm.txt", ARTIFACTS_DIR / "susceptibility_calibration.json")
    susceptibility, _info = predict_map(fitted, MODEL_FEATURES, stack_path)
    write_map(susceptibility_path, susceptibility, stack_path, method="regional LightGBM")
    valid = susceptibility[np.isfinite(susceptibility)]
    if valid.size == 0:
        raise SystemExit("susceptibility map has no cells")
    print(f"wrote {rel(susceptibility_path)}: {int(valid.size)} cells, mean {float(valid.mean()):.4f}")

    rain = get_hourly_rain(lat, lon)
    result = run_model_b(rain, path=susceptibility_path)
    grid = ProbabilityMap(
        np.asarray(result.probability, dtype="float32"), result.transform, str(result.crs), HILL_METHOD,
    )
    write_probability(grid, probability_path)
    scored = grid.values[np.isfinite(grid.values)]
    print(
        f"wrote {rel(probability_path)} ({HILL_METHOD}): "
        f"mean {float(scored.mean()):.4f}, max {float(scored.max()):.4f}, "
        f"rain next 72h {rain.total(0, 72):.1f} mm at {lat}, {lon}"
    )

    tiles = slug_tiles_dir(TURTLE_SLUG)
    for layer, raster in (("susceptibility", susceptibility_path), ("probability", probability_path)):
        metadata = render_xyz(raster, layer, bbox=TURTLE_BBOX, tiles_dir=tiles)
        print(f"rendered {metadata['tile_count']} {layer} tiles into {rel(tiles / layer)}")


if __name__ == "__main__":
    main()
