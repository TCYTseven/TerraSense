#!/usr/bin/env python3
"""Build the regional terrain features and landslide labels for the susceptibility model.

Reads data/raw/region_*.tif (download_region.py) and the USGS Landslide Inventories across the
United States v3 CSVs in data/raw/usgs_v3/, and writes, relative to the repo root:
  data/processed/regional_labels.parquet        labeled pixels: training rows from the region
                                                (Rainier box plus RAINIER_HOLDOUT_BUFFER_M left
                                                out) and external test rows inside the Rainier box
  data/processed/rainier_regional_features.tif  the same features on the legacy Rainier grid
                                                (EPSG:32610, 30 m, 1004 x 757), for the map
  data/processed/regional_features.tif          the whole regional stack, only with --write-stack

Features are computed once on a regional 30 m UTM grid snapped to whole 30 m multiples, so the
legacy Rainier grid is an exact window of it and the map sees the same upstream flow routing and
neighborhoods as the training pixels.

Run from the repo root:
  python ml/scripts/build_regional_features.py [--write-stack]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine, rowcol
from rasterio.warp import Resampling, transform_bounds
from scipy.ndimage import distance_transform_edt, maximum_filter, minimum_filter, uniform_filter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_features import (  # noqa: E402
    CELL_M, CHANNEL_AREA_M2, curvature, fill_nearest, flow_accumulation, neighbors, resample, slope_aspect,
    utm_grid,
)
from mountain_packs import RAINIER_BBOX  # noqa: E402
from download_region import DOWNLOAD_BBOX, REGION_BBOX, REGION_DEM_PATH, REGION_LANDCOVER_PATH  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RAINIER_DEM_PATH = REPO_ROOT / "data" / "raw" / "rainier_dem_cop30.tif"
RAINIER_LANDCOVER_PATH = REPO_ROOT / "data" / "raw" / "rainier_landcover_worldcover2021.tif"
GRID_CRS = "EPSG:32610"  # Rainier's UTM zone, the grid the live app scores on
USGS_DIR = REPO_ROOT / "data" / "raw" / "usgs_v3" / "US_Landslide_v3_csv"
USGS_FILES = {"poly": USGS_DIR / "us_ls_v3_poly.csv", "point": USGS_DIR / "us_ls_v3_point.csv"}
SEED_LANDSLIDES = REPO_ROOT / "data" / "seed" / "landslides.geojson"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
TABLE_PATH = PROCESSED_DIR / "regional_labels.parquet"
RAINIER_STACK_PATH = PROCESSED_DIR / "rainier_regional_features.tif"
REGION_STACK_PATH = PROCESSED_DIR / "regional_features.tif"

# Band order of the regional stack. Elevation stays in the stack for diagnostics; whether the
# model uses it is decided in train_regional_susceptibility.py.
FEATURES = [
    "elevation", "slope", "aspect_sin", "aspect_cos", "curvature", "profile_curvature",
    "plan_curvature", "dist_drainage", "twi", "landcover",
    "relief_150", "relief_500", "relief_1000", "tpi_500", "tpi_1000", "roughness_90", "slope_std_150",
]
# Window radii in meters for the neighborhood descriptors. relief_R is max minus min elevation in
# a square of half-width R; tpi_R is elevation minus the window mean.
RELIEF_RADII_M = (150, 500, 1000)
TPI_RADII_M = (500, 1000)
SLOPE_STD_RADIUS_M = 150

# Cells at or below this elevation that WorldCover calls water are Puget Sound. They are left out
# of flow routing, where one huge flat would dominate the run time.
SEA_LEVEL_M = 0.5
WATER_CLASS = 80

# USGS v3 confidence (metadata of doi:10.5066/P14AJF8I): 1 possible landslide in the area,
# 2 probable landslide in the area (geologic-map deposits that may merge several slides),
# 3 likely landslide at or near this location, 5 moderate and 8 high confidence in its extent.
# Positives need 3 or more: the record says a landslide is at this location.
MIN_CONFIDENCE = 3
# Positives come from one inventory family so mapping practice is uniform across the region.
TRAIN_INVENTORY = "WA WGS"
# Sources and types kept out of the positives (they still exclude negatives):
EXCLUDED_SOURCE_PATTERN = "Marine shore"   # Puget Sound shoreline bluffs, not mountain terrain
EXCLUDED_TYPES = {"fan"}                    # depositional fans, not failure sources
# Snow and ice movements are not earth or rock landslides.
NON_LANDSLIDE_TYPES = {"snow avalanche", "ice avalanche", "ice fall"}
# The seed's high-accuracy points (the old training labels) join the Rainier external test set.
SEED_ACCURACIES = {"exact", "1km"}

# One positive per THIN_CELLS x THIN_CELLS block (90 m), so one mapped slide is not counted as
# many near-identical pixels.
THIN_CELLS = 3
# Negatives: farther than this from every record in the full inventory, any confidence or type.
NEGATIVE_EXCLUSION_M = 500
NEGATIVES_PER_POSITIVE = 3
# Absence of a record only means stable ground where someone mapped. Negatives are drawn from
# FOOTPRINT_CELL_M squares holding at least FOOTPRINT_MIN_RECORDS WA WGS records at the minimum
# confidence (fans and all types included), a proxy for the inventory's mapped footprint.
FOOTPRINT_CELL_M = 5000
FOOTPRINT_MIN_RECORDS = 3
# The Rainier grid plus this buffer is left out of training entirely.
RAINIER_HOLDOUT_BUFFER_M = 2000
RANDOM_SEED = 26


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def snapped_grid(bbox, crs: str = GRID_CRS) -> tuple[Affine, int, int]:
    """A CELL_M grid covering bbox, with edges on whole multiples of CELL_M (as utm_grid())."""
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
    left, bottom = np.floor(left / CELL_M) * CELL_M, np.floor(bottom / CELL_M) * CELL_M
    right, top = np.ceil(right / CELL_M) * CELL_M, np.ceil(top / CELL_M) * CELL_M
    return Affine(CELL_M, 0, left, 0, -CELL_M, top), int((right - left) / CELL_M), int((top - bottom) / CELL_M)


def rainier_window(region_transform: Affine) -> tuple[int, int, int, int]:
    """(row_off, col_off, height, width) of the legacy Rainier grid inside the regional grid."""
    rainier_transform, width, height = utm_grid(RAINIER_BBOX, GRID_CRS)
    col = (rainier_transform.c - region_transform.c) / CELL_M
    row = (region_transform.f - rainier_transform.f) / CELL_M
    if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
        raise SystemExit("the Rainier grid is not an exact window of the regional grid")
    return int(round(row)), int(round(col)), height, width


def plan_profile_curvature(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Zevenbergen and Thorne (1987) profile and plan curvature, ArcGIS sign and 1/100 m units."""
    a, b, c, d, e, f, g, h, i = neighbors(z)
    L = CELL_M
    D = ((d + f) / 2 - e) / L**2
    E = ((b + h) / 2 - e) / L**2
    F = (-a + c + g - i) / (4 * L**2)
    G = (-d + f) / (2 * L)
    H = (b - h) / (2 * L)
    gh = G**2 + H**2
    safe = np.where(gh > 1e-10, gh, 1.0)
    profile = np.where(gh > 1e-10, -200 * (D * G**2 + E * H**2 + F * G * H) / safe, 0.0)
    plan = np.where(gh > 1e-10, 200 * (D * H**2 + E * G**2 - F * G * H) / safe, 0.0)
    return profile.astype("float32"), plan.astype("float32")


def window_cells(radius_m: float) -> int:
    return 2 * int(round(radius_m / CELL_M)) + 1


def build_stack(
    dst_transform: Affine,
    shape: tuple[int, int],
    *,
    dem_path: Path = REGION_DEM_PATH,
    landcover_path: Path = REGION_LANDCOVER_PATH,
) -> np.ndarray:
    """All FEATURES on the regional grid, shape (len(FEATURES), rows, cols), NaN outside the DEM."""
    stack = np.full((len(FEATURES),) + shape, np.nan, dtype="float32")
    put = lambda name, values: stack.__setitem__(FEATURES.index(name), values)  # noqa: E731

    elevation = resample(dem_path, dst_transform, shape, GRID_CRS, Resampling.bilinear, "float32")
    elevation[elevation <= -1000] = np.nan
    landcover = resample(landcover_path, dst_transform, shape, GRID_CRS, Resampling.mode, "uint8").astype("float32")
    landcover[landcover == 0] = np.nan
    put("elevation", elevation)
    put("landcover", landcover)

    filled = fill_nearest(elevation)
    slope, aspect = slope_aspect(filled)
    put("slope", slope)
    radians = np.radians(aspect)
    put("aspect_sin", np.where(np.isnan(aspect), 0, np.sin(radians)).astype("float32"))
    put("aspect_cos", np.where(np.isnan(aspect), 0, np.cos(radians)).astype("float32"))
    del aspect, radians
    put("curvature", curvature(filled))
    profile, plan = plan_profile_curvature(filled)
    put("profile_curvature", profile)
    put("plan_curvature", plan)
    del profile, plan

    sea = (landcover == WATER_CLASS) & (elevation <= SEA_LEVEL_M)
    accumulation = flow_accumulation(np.where(sea, np.nan, elevation), dst_transform, GRID_CRS)
    channels = accumulation * CELL_M**2 >= CHANNEL_AREA_M2
    put("dist_drainage", (distance_transform_edt(~channels) * CELL_M).astype("float32"))
    tan_slope = np.tan(np.radians(np.maximum(slope, 0.1)))
    put("twi", np.log(np.maximum(accumulation, 1) * CELL_M / tan_slope).astype("float32"))
    del accumulation, channels, tan_slope

    for radius in RELIEF_RADII_M:
        size = window_cells(radius)
        put(f"relief_{radius}", maximum_filter(filled, size=size) - minimum_filter(filled, size=size))
    for radius in TPI_RADII_M:
        put(f"tpi_{radius}", filled - uniform_filter(filled.astype("float64"), size=window_cells(radius)).astype("float32"))
    mean3 = uniform_filter(filled.astype("float64"), size=3)
    put("roughness_90", np.sqrt(np.maximum(uniform_filter(filled.astype("float64") ** 2, size=3) - mean3**2, 0)))
    size = window_cells(SLOPE_STD_RADIUS_M)
    s64 = slope.astype("float64")
    mean_s = uniform_filter(s64, size=size)
    put("slope_std_150", np.sqrt(np.maximum(uniform_filter(s64**2, size=size) - mean_s**2, 0)))

    stack[:, np.isnan(elevation)] = np.nan
    return stack


def read_inventory(files: dict[str, Path] = USGS_FILES, bbox=DOWNLOAD_BBOX) -> pd.DataFrame:
    """USGS v3 records in bbox, one row each, with lon normalized to negative (west)."""
    frames = []
    for kind, path in files.items():
        table = pd.read_csv(path, low_memory=False,
                            usecols=["USGS_ID", "Confidence", "LS_Type", "Inventory", "Info_Source", "Lat_N", "Lon_W"])
        table["lon"] = table["Lon_W"].where(table["Lon_W"] < 0, -table["Lon_W"])
        table["lat"] = table["Lat_N"]
        table["kind"] = kind
        frames.append(table)
    records = pd.concat(frames, ignore_index=True)
    west, south, east, north = bbox
    records = records[records["lon"].between(west, east) & records["lat"].between(south, north)]
    return records.dropna(subset=["lon", "lat"]).reset_index(drop=True)


def in_bbox(lon, lat, bbox) -> np.ndarray:
    west, south, east, north = bbox
    return (np.asarray(lon) >= west) & (np.asarray(lon) <= east) & (np.asarray(lat) >= south) & (np.asarray(lat) <= north)


def training_positive_mask(records: pd.DataFrame) -> pd.Series:
    """Records eligible as training positives: one inventory, minimum confidence, no fans or shoreline."""
    types = records["LS_Type"].fillna("").str.strip().str.lower()
    return ((records["Inventory"] == TRAIN_INVENTORY) & (records["Confidence"] >= MIN_CONFIDENCE)
            & ~records["Info_Source"].fillna("").str.contains(EXCLUDED_SOURCE_PATTERN)
            & ~types.isin(EXCLUDED_TYPES) & ~types.isin(NON_LANDSLIDE_TYPES))


def footprint_mask(records: pd.DataFrame) -> pd.Series:
    """Records that show where the WA WGS inventory mapped, for the negative-sampling footprint."""
    return ((records["Inventory"] == TRAIN_INVENTORY) & (records["Confidence"] >= MIN_CONFIDENCE)
            & ~records["Info_Source"].fillna("").str.contains(EXCLUDED_SOURCE_PATTERN))


def external_positive_mask(records: pd.DataFrame) -> pd.Series:
    """Records inside the Rainier box used as external positives: any inventory, minimum confidence."""
    types = records["LS_Type"].fillna("").str.strip().str.lower()
    return (in_bbox(records["lon"], records["lat"], RAINIER_BBOX) & (records["Confidence"] >= MIN_CONFIDENCE)
            & ~types.isin(NON_LANDSLIDE_TYPES) & ~types.isin(EXCLUDED_TYPES))


def seed_points(path: Path = SEED_LANDSLIDES) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=["lon", "lat", "Inventory", "Confidence", "LS_Type", "USGS_ID"])
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    rows = [{"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
             "Inventory": f"seed: {f['properties'].get('catalog')}", "Confidence": np.nan,
             "LS_Type": f["properties"].get("category"), "USGS_ID": f"seed{f['properties'].get('id')}"}
            for f in features if (f["properties"].get("location_accuracy") or "").lower() in SEED_ACCURACIES]
    return pd.DataFrame(rows)


def to_cells(lon, lat, dst_transform: Affine, shape) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grid row, col for each lon/lat, and whether it falls on the grid."""
    xs, ys = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True).transform(np.asarray(lon), np.asarray(lat))
    rows, cols = rowcol(dst_transform, xs, ys)
    rows, cols = np.asarray(rows), np.asarray(cols)
    inside = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    return rows, cols, inside


def thin(rows: np.ndarray, cols: np.ndarray, cells: int = THIN_CELLS) -> np.ndarray:
    """Index of the first record in each cells x cells block, so clusters count once."""
    keys = pd.DataFrame({"r": rows // cells, "c": cols // cells})
    return np.flatnonzero(~keys.duplicated().to_numpy())


def distance_to(seed_rows, seed_cols, shape) -> np.ndarray:
    """Meters from every cell to the nearest seed cell."""
    seeds = np.zeros(shape, dtype=bool)
    seeds[seed_rows, seed_cols] = True
    return (distance_transform_edt(~seeds) * CELL_M).astype("float32")


def footprint(seed_rows, seed_cols, shape, cell_m: int = FOOTPRINT_CELL_M,
              min_records: int = FOOTPRINT_MIN_RECORDS) -> np.ndarray:
    """True where the enclosing cell_m square holds at least min_records mapped records."""
    step = cell_m // CELL_M
    counts = np.zeros((shape[0] // step + 1, shape[1] // step + 1), dtype=np.int32)
    np.add.at(counts, (seed_rows // step, seed_cols // step), 1)
    mapped = counts >= min_records
    rr = np.arange(shape[0]) // step
    cc = np.arange(shape[1]) // step
    return mapped[rr[:, None], cc[None, :]]


def sample_negatives(candidates: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """n flat indices drawn without replacement from a boolean candidate mask."""
    flat = np.flatnonzero(candidates)
    return rng.choice(flat, size=min(n, flat.size), replace=False)


def cell_lonlat(dst_transform: Affine, shape) -> tuple[np.ndarray, np.ndarray]:
    """Lon/lat of every cell center, computed per row block to bound memory."""
    to_ll = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
    lon = np.empty(shape, dtype="float32")
    lat = np.empty(shape, dtype="float32")
    xs = dst_transform.c + (np.arange(shape[1]) + 0.5) * CELL_M
    for r0 in range(0, shape[0], 512):
        r1 = min(r0 + 512, shape[0])
        ys = dst_transform.f - (np.arange(r0, r1) + 0.5) * CELL_M
        X, Y = np.meshgrid(xs, ys)
        lo, la = to_ll.transform(X, Y)
        lon[r0:r1], lat[r0:r1] = lo, la
    return lon, lat


def build_labels(stack: np.ndarray, dst_transform: Affine) -> tuple[pd.DataFrame, dict]:
    shape = stack.shape[1:]
    rng = np.random.default_rng(RANDOM_SEED)
    records = read_inventory()
    rows, cols, inside = to_cells(records["lon"], records["lat"], dst_transform, shape)
    records = records[inside].assign(row=rows[inside], col=cols[inside]).reset_index(drop=True)

    required = [FEATURES.index(n) for n in FEATURES]
    valid = ~np.isnan(stack[required]).any(axis=0) & (stack[FEATURES.index("landcover")] != WATER_CLASS)
    lon, lat = cell_lonlat(dst_transform, shape)
    in_region = in_bbox(lon, lat, REGION_BBOX)
    in_rainier = in_bbox(lon, lat, RAINIER_BBOX)
    del lon, lat
    r0, c0, h, w = rainier_window(dst_transform)
    pad = -(-RAINIER_HOLDOUT_BUFFER_M // CELL_M)  # whole cells, rounded up so the buffer is never short
    holdout = np.zeros(shape, dtype=bool)
    holdout[max(r0 - pad, 0):r0 + h + pad, max(c0 - pad, 0):c0 + w + pad] = True

    seeds = seed_points()
    srows, scols, sinside = to_cells(seeds["lon"], seeds["lat"], dst_transform, shape)
    seeds = seeds[sinside].assign(row=srows[sinside], col=scols[sinside])
    all_rows = np.concatenate([records["row"].to_numpy(), seeds["row"].to_numpy()])
    all_cols = np.concatenate([records["col"].to_numpy(), seeds["col"].to_numpy()])
    dist_any = distance_to(all_rows, all_cols, shape)
    fp = records[footprint_mask(records)]
    mapped = footprint(fp["row"].to_numpy(), fp["col"].to_numpy(), shape)

    def positives(candidates: pd.DataFrame, allowed: np.ndarray) -> pd.DataFrame:
        ok = allowed[candidates["row"].to_numpy(), candidates["col"].to_numpy()]
        kept = candidates[ok].reset_index(drop=True)
        return kept.iloc[thin(kept["row"].to_numpy(), kept["col"].to_numpy())].reset_index(drop=True)

    train_pos = positives(records[training_positive_mask(records)], valid & in_region & ~holdout)
    external_candidates = pd.concat([records[external_positive_mask(records)], seeds], ignore_index=True)
    ext_pos = positives(external_candidates, valid & in_rainier)

    neg_rule = valid & (dist_any > NEGATIVE_EXCLUSION_M) & mapped
    train_neg = sample_negatives(neg_rule & in_region & ~holdout, NEGATIVES_PER_POSITIVE * len(train_pos), rng)
    ext_neg = sample_negatives(neg_rule & in_rainier, NEGATIVES_PER_POSITIVE * len(ext_pos), rng)

    parts = []
    for name, pos, neg in (("train", train_pos, train_neg), ("external", ext_pos, ext_neg)):
        nr, nc = np.unravel_index(neg, shape)
        part = pd.DataFrame({
            "row": np.concatenate([pos["row"].to_numpy(), nr]).astype("int32"),
            "col": np.concatenate([pos["col"].to_numpy(), nc]).astype("int32"),
            "label": np.r_[np.ones(len(pos)), np.zeros(len(nr))].astype("int8"),
            "source": np.r_[pos["Inventory"].astype(str).to_numpy(), np.full(len(nr), "negative")],
            "confidence": np.r_[pos["Confidence"].to_numpy(dtype=float), np.full(len(nr), np.nan)],
            "set": name,
        })
        parts.append(part)
    table = pd.concat(parts, ignore_index=True)
    for i, name in enumerate(FEATURES):
        table[name] = stack[i, table["row"], table["col"]]
    table["x"] = dst_transform.c + (table["col"] + 0.5) * CELL_M
    table["y"] = dst_transform.f - (table["row"] + 0.5) * CELL_M
    table["dist_any_record_m"] = dist_any[table["row"], table["col"]]

    tr = training_positive_mask(records)
    summary = {
        "inventory_records_in_download_bbox": int(len(records)),
        "records_by_confidence": {str(k): int(v) for k, v in records["Confidence"].value_counts().sort_index().items()},
        "training_eligible_records": int((tr & in_region[records["row"], records["col"]]
                                          & ~holdout[records["row"], records["col"]]).sum()),
        "training_positives_after_thinning": int(len(train_pos)),
        "training_negatives": int(len(train_neg)),
        "training_positives_by_confidence": {str(k): int(v) for k, v in
                                             train_pos["Confidence"].value_counts().sort_index().items()},
        "external_positive_records": int(len(external_candidates[in_rainier[external_candidates["row"],
                                                                             external_candidates["col"]]])),
        "external_positives_after_thinning": int(len(ext_pos)),
        "external_negatives": int(len(ext_neg)),
        "external_positives_by_source": {k: int(v) for k, v in ext_pos["Inventory"].value_counts().items()},
        "mapped_footprint_share_of_region": round(float(mapped[in_region & valid].mean()), 4),
        "negative_candidates_region": int((neg_rule & in_region & ~holdout).sum()),
        "negative_candidates_rainier": int((neg_rule & in_rainier).sum()),
    }
    return table, summary


def write_stack(path: Path, stack: np.ndarray, dst_transform: Affine) -> None:
    profile = {
        "driver": "GTiff", "width": stack.shape[2], "height": stack.shape[1], "count": len(FEATURES),
        "dtype": "float32", "crs": GRID_CRS, "transform": dst_transform, "nodata": np.nan,
        "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate", "predictor": 3,
        "BIGTIFF": "IF_SAFER",
    }
    partial = path.with_name(path.name + ".part")
    with rasterio.open(partial, "w", **profile) as dst:
        dst.write(stack)
        for band, name in enumerate(FEATURES, start=1):
            dst.set_band_description(band, name)
        dst.update_tags(CHANNEL_AREA_M2=CHANNEL_AREA_M2, SOURCE="ml/scripts/build_regional_features.py")
    partial.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build regional features and landslide labels.")
    parser.add_argument("--write-stack", action="store_true",
                        help=f"also write the whole regional stack to {rel(REGION_STACK_PATH)} (~1 GB)")
    parser.add_argument(
        "--rainier-stack-only",
        action="store_true",
        help=f"build only {rel(RAINIER_STACK_PATH)} from the Rainier step-10 rasters (no regional download)",
    )
    args = parser.parse_args()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if args.rainier_stack_only:
        for path in (RAINIER_DEM_PATH, RAINIER_LANDCOVER_PATH):
            if not path.is_file():
                raise SystemExit(f"{rel(path)} is missing (run ml/scripts/download_sources.py for Rainier)")
        dst_transform, width, height = utm_grid(RAINIER_BBOX, GRID_CRS)
        print(f"Rainier-only stack {width} x {height} at {CELL_M} m, {GRID_CRS}")
        stack = build_stack(dst_transform, (height, width), dem_path=RAINIER_DEM_PATH,
                            landcover_path=RAINIER_LANDCOVER_PATH)
        write_stack(RAINIER_STACK_PATH, stack, dst_transform)
        print(f"wrote {rel(RAINIER_STACK_PATH)} ({RAINIER_STACK_PATH.stat().st_size / 1e6:.1f} MB)")
        return

    dst_transform, width, height = snapped_grid(DOWNLOAD_BBOX)
    print(f"regional grid {width} x {height} cells at {CELL_M} m, {GRID_CRS}, origin ({dst_transform.c}, {dst_transform.f})")
    stack = build_stack(dst_transform, (height, width))
    for i, name in enumerate(FEATURES):
        print(f"  {name:<18} min {np.nanmin(stack[i]):10.2f}  median {np.nanmedian(stack[i]):10.2f}  max {np.nanmax(stack[i]):10.2f}")

    r0, c0, h, w = rainier_window(dst_transform)
    rainier_transform, _, _ = utm_grid()
    write_stack(RAINIER_STACK_PATH, stack[:, r0:r0 + h, c0:c0 + w], rainier_transform)
    print(f"wrote {rel(RAINIER_STACK_PATH)}: {w} x {h}, window at row {r0}, col {c0} "
          f"({RAINIER_STACK_PATH.stat().st_size / 1e6:.1f} MB)")
    if args.write_stack:
        write_stack(REGION_STACK_PATH, stack, dst_transform)
        print(f"wrote {rel(REGION_STACK_PATH)} ({REGION_STACK_PATH.stat().st_size / 1e6:.1f} MB)")

    table, summary = build_labels(stack, dst_transform)
    table.to_parquet(TABLE_PATH, index=False)
    print(f"wrote {rel(TABLE_PATH)}: {len(table)} rows ({TABLE_PATH.stat().st_size / 1e6:.1f} MB)")
    print(json.dumps(summary, indent=2))
    (PROCESSED_DIR / "regional_labels_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
