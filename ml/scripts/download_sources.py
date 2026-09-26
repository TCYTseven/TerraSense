#!/usr/bin/env python3
"""Download one mountain's source layers (implementation steps 10 and 32).

For Mount Rainier (the default) this writes, relative to the repo root:
  data/raw/rainier_dem_cop30.tif                 Copernicus DEM GLO-30 clipped to the bbox
  data/raw/rainier_landcover_worldcover2021.tif  ESA WorldCover 2021 v200 clipped to the bbox
  data/seed/landslides.geojson                   NASA GLC or Washington inventory points in the bbox

For any other pack in ml/scripts/mountain_packs.py, the same three layers land under
data/raw/packs/<slug>/ and data/seed/packs/<slug>/. A bbox that crosses a COG tile edge
mosaics the tiles it touches. The Washington inventory fallback is Rainier's alone; other
packs keep whatever NASA GLC holds in their box, including nothing (the record card may
honestly say the catalog is empty there).

Rasters keep their native CRS (EPSG:4326). Step 11 builds the common 30 m grid.
Source URLs, licences, and access dates live in data/seed/sources.md.

Run from the repo root:
  python ml/scripts/download_sources.py [--mountain SLUG] [--only dem,landcover,landslides] [--force]

The default NASA GLC export is preferred. If its host is unavailable, the script queries the
official Washington Geological Survey Landslide Compilation ArcGIS layer instead. If an available
NASA export has fewer than two usable high-accuracy points, the Washington inventory supplements
it so the spatially held-out model does not train on a single event cluster; no labels are
invented locally.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import mountain_packs as mp
import numpy as np
import rasterio
import requests
from rasterio.enums import ColorInterp
from rasterio.merge import merge
from rasterio.windows import Window, bounds as window_bounds, from_bounds
from shapely.geometry import box, shape

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
SEED_DIR = REPO_ROOT / "data" / "seed"

# NASA Global Landslide Catalog, full CSV export of data.nasa.gov dataset dd9e-wu2v.
# One cached download serves every pack; each pack filters it to its own bbox.
GLC_CSV_URL = "https://data.nasa.gov/api/views/dd9e-wu2v/rows.csv?accessType=DOWNLOAD"
# Washington Geological Survey's official Landslide Compilation layer. It is a polygon
# inventory, so the fallback uses an interior representative point as a conservative label.
WASLID_QUERY_URL = (
    "https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/131/query"
)
WASLID_LAYER_URL = WASLID_QUERY_URL.removesuffix("/query")

GLC_CSV_PATH = RAW_DIR / "nasa_glc_export.csv"

DEM_ATTRIBUTION = (
    "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under "
    "COPERNICUS by the European Union and ESA; all rights reserved"
)
LANDCOVER_ATTRIBUTION = (
    "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) "
    "processed by ESA WorldCover consortium (CC BY 4.0)"
)

WORLDCOVER_CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

# GeoJSON property -> NASA GLC export column.
GLC_FIELDS = {
    "id": "event_id",
    "date": "event_date",
    "title": "event_title",
    "category": "landslide_category",
    "trigger": "landslide_trigger",
    "size": "landslide_size",
    "setting": "landslide_setting",
    "location_accuracy": "location_accuracy",
    "fatalities": "fatality_count",
    "source_name": "source_name",
    "source_link": "source_link",
}

STAGES = ("dem", "landcover", "landslides")
WASLID_SOURCE_NAME = "Washington State Landslide Inventory Database — Landslide Compilation"
TRAINING_ACCURACIES = {"exact", "1km"}


def rel(path: Path) -> str:
    """Path relative to the repo root, for log lines."""
    return str(path.relative_to(REPO_ROOT))


def covers(bounds, bbox, tol=1e-9) -> bool:
    """True if raster bounds (left, bottom, right, top) contain bbox (west, south, east, north)."""
    left, bottom, right, top = bounds
    west, south, east, north = bbox
    return left <= west + tol and bottom <= south + tol and right >= east - tol and top >= north - tol


def gdal_env() -> rasterio.Env:
    """GDAL options for reading a window of a remote COG with a few HTTP range requests."""
    options = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",  # no bucket listing or sidecar probes
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_TIMEOUT": "60",
    }
    # rasterio points GDAL at certifi's CA bundle. Prefer a bundle the environment
    # names, e.g. behind a TLS-inspecting proxy. Verification always stays on.
    ca_bundle = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle:
        options["GDAL_CURL_CA_BUNDLE"] = ca_bundle
    return rasterio.Env(**options)


def bbox_window(src, bbox) -> Window:
    """Pixel window on src's grid that covers bbox, grown outward to whole pixels.

    The window may reach past src's own bounds; it only fixes where the pixels sit.
    """
    w = from_bounds(*bbox, transform=src.transform)
    # Round before floor/ceil so float noise on an exact pixel edge adds no pixel.
    col0, row0 = math.floor(round(w.col_off, 6)), math.floor(round(w.row_off, 6))
    col1, row1 = math.ceil(round(w.col_off + w.width, 6)), math.ceil(round(w.row_off + w.height, 6))
    return Window(col0, row0, col1 - col0, row1 - row0)


def clip_cogs(urls: list[str], bbox, out_path: Path, attribution: str, **creation) -> None:
    """Read the bbox window from one or more remote COG tiles and save it as one GeoTIFF.

    A single covering tile reads its window directly, exactly as step 10 always has. A bbox
    that crosses tile edges mosaics every tile it touches; each product's tiles share one
    global grid, so the merged pixels sit where a single-tile read would put them.
    """
    with gdal_env():
        sources = [rasterio.open(f"/vsicurl/{url}") for url in urls]
        try:
            first = sources[0]
            window = bbox_window(first, bbox)
            if len(sources) == 1:
                if not covers(first.bounds, bbox):
                    raise ValueError(f"{urls[0]} bounds {tuple(first.bounds)} do not contain {bbox}")
                data = first.read(1, window=window)
                transform = first.window_transform(window)
            else:
                snapped = window_bounds(window, first.transform)  # whole pixels on the shared grid
                mosaic, transform = merge(sources, bounds=snapped, res=first.res, nodata=first.nodata)
                data = mosaic[0]
            profile = dict(first.profile)
            profile.update(
                driver="GTiff",
                width=data.shape[1],
                height=data.shape[0],
                transform=transform,
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress="deflate",
                **creation,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = out_path.with_name(out_path.name + ".part")
            with rasterio.open(tmp_path, "w", **profile) as dst:
                dst.write(data, 1)
                dst.update_tags(**first.tags(), SOURCE_URL=", ".join(urls), ATTRIBUTION=attribution)
                if first.colorinterp[0] == ColorInterp.palette:
                    dst.write_colormap(1, first.colormap(1))
        finally:
            for src in sources:
                src.close()
    tmp_path.replace(out_path)  # only a finished file counts as done


def dem_summary(ds, pack: mp.Pack) -> str:
    """Elevation range, and where the highest pixel sits next to the pack's summit fact."""
    z = ds.read(1, masked=True)
    row, col = np.unravel_index(np.ma.argmax(z), z.shape)
    lon, lat = ds.xy(row, col)
    return (
        f"elevation min {z.min():.1f} m, max {z.max():.1f} m at ({lat:.4f}, {lon:.4f}), "
        f"{z.max() - pack.peak_elevation_m:+.1f} m vs shared peak {pack.peak_elevation_m} m "
        f"at ({pack.peak_lat}, {pack.peak_lon})"
    )


def landcover_summary(ds, pack: mp.Pack) -> str:
    """Class histogram with WorldCover class names."""
    values, counts = np.unique(ds.read(1), return_counts=True)
    lines = ["classes (code, name, share of pixels):"]
    for value, count in zip(values.tolist(), counts.tolist(), strict=True):
        name = "no data" if value == ds.nodata else WORLDCOVER_CLASSES.get(value, "unknown")
        lines.append(f"    {value:>3} {name:<24} {count / counts.sum():6.1%}")
    return "\n".join(lines)


def verify_raster(path: Path, summarize, pack: mp.Pack) -> None:
    """Print CRS, size, pixel size, bounds, nodata and a value summary. Fail if the bbox is not covered."""
    with rasterio.open(path) as ds:
        b = ds.bounds
        lat = math.radians((b.top + b.bottom) / 2)
        px_m = (ds.res[0] * 111_320 * math.cos(lat), ds.res[1] * 111_320)
        print(
            f"  verify {rel(path)}: CRS {ds.crs}, {ds.width} x {ds.height} px, "
            f"pixel {ds.res[0]:.8f} x {ds.res[1]:.8f} deg (~{px_m[0]:.1f} x {px_m[1]:.1f} m), "
            f"bounds ({b.left:.6f}, {b.bottom:.6f}, {b.right:.6f}, {b.top:.6f}), nodata {ds.nodata}"
        )
        print(f"  {summarize(ds, pack)}")
        if not covers(b, pack.bbox):
            raise AssertionError(f"{rel(path)} bounds {tuple(b)} do not cover the bbox {pack.bbox}")
        print(f"  bounds cover bbox {list(pack.bbox)}: OK")


def fetch_raster(urls: list[str], path: Path, attribution: str, summarize, pack: mp.Pack,
                 force: bool, **creation) -> None:
    """Clip urls into path unless it already exists (or force), then verify the file."""
    if path.exists() and not force:
        print(f"  {rel(path)} exists, skipping download (use --force to refresh)")
    else:
        print(f"  reading bbox window from {len(urls)} tile(s): {', '.join(urls)}")
        clip_cogs(urls, pack.bbox, path, attribution, **creation)
        print(f"  wrote {rel(path)} ({path.stat().st_size / 1e6:.1f} MB)")
    verify_raster(path, summarize, pack)


def stage_dem(force: bool, pack: mp.Pack, paths: mp.PackPaths) -> None:
    """Copernicus DEM GLO-30: float32 metres above the EGM2008 geoid, 1 arcsec, EPSG:4326."""
    fetch_raster(pack.dem_urls, paths.dem, DEM_ATTRIBUTION, dem_summary, pack, force, predictor=3)


def stage_landcover(force: bool, pack: mp.Pack, paths: mp.PackPaths) -> None:
    """ESA WorldCover 2021 v200: uint8 class codes, 0.3 arcsec (~10 m), EPSG:4326, nodata 0."""
    fetch_raster(pack.landcover_urls, paths.landcover, LANDCOVER_ATTRIBUTION, landcover_summary, pack, force)


def download(url: str, path: Path) -> None:
    """Stream url to path. The error names the host if it cannot be reached."""
    host = urlparse(url).hostname
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except requests.RequestException as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"cannot download from host {host}: {type(exc).__name__}: {exc}\n"
            f"  If this network blocks {host}, download {url} elsewhere "
            f"and rerun with --glc-csv PATH."
        ) from exc
    tmp_path.replace(path)


def iso_date(value: str) -> str | None:
    """GLC timestamp ('08/01/2008 12:00:00 AM' in CSV, ISO in JSON) to 'YYYY-MM-DD'."""
    value = value.strip()
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def as_int(value: str | None) -> int | str | None:
    """Integer if the text is a whole number, else the text unchanged."""
    try:
        return int(float(value)) if value else None
    except ValueError:
        return value


def glc_features(csv_path: Path, bbox) -> list[dict]:
    """GeoJSON Point features for NASA GLC events inside bbox, oldest first."""
    west, south, east, north = bbox
    features = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"latitude", "longitude", *GLC_FIELDS.values()} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is not a NASA GLC export CSV (missing columns: {sorted(missing)})")
        for row in reader:
            try:
                lon, lat = float(row["longitude"]), float(row["latitude"])
            except (TypeError, ValueError):  # blank, short, or non-numeric row
                continue
            if not (west <= lon <= east and south <= lat <= north):
                continue
            props = {key: (row[column] or "").strip() or None for key, column in GLC_FIELDS.items()}
            props["id"] = as_int(props["id"])
            props["fatalities"] = as_int(props["fatalities"])
            props["date"] = iso_date(row["event_date"] or "")
            props["catalog"] = "NASA Global Landslide Catalog"
            features.append({
                "type": "Feature",
                "id": props["id"],
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": props,
            })
    return sorted(features, key=lambda feature: feature["properties"]["date"] or "")


def usable_training_features(features: list[dict]) -> list[dict]:
    """Return catalog points precise enough to become 30 m pixel labels."""
    return [feature for feature in features
            if (feature["properties"].get("location_accuracy") or "").lower() in TRAINING_ACCURACIES]


def merge_catalog_features(primary: list[dict], supplemental: list[dict]) -> list[dict]:
    """Combine catalogs without dropping provenance or duplicating the same catalog id."""
    seen = {
        (feature["properties"].get("catalog"), str(feature.get("id")))
        for feature in primary
    }
    merged = list(primary)
    for feature in supplemental:
        key = (feature["properties"].get("catalog"), str(feature.get("id")))
        if key not in seen:
            merged.append(feature)
            seen.add(key)
    return sorted(merged, key=lambda feature: feature["properties"].get("date") or "")


def _arcgis_date(value) -> str | None:
    """Convert an ArcGIS epoch-millisecond or ISO date into the seed's YYYY-MM-DD value."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC).date().isoformat()
    return iso_date(str(value))


def waslid_features(payload: dict, bbox) -> list[dict]:
    """Convert WGS polygon features into representative point labels inside the Rainier bbox."""
    if payload.get("type") != "FeatureCollection":
        message = payload.get("error", {}).get("message", "not a GeoJSON FeatureCollection")
        raise ValueError(f"WASLID query did not return GeoJSON: {message}")

    west, south, east, north = bbox
    clip = box(west, south, east, north)
    features = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        clipped = shape(geometry).intersection(clip)
        if clipped.is_empty:
            continue
        point = clipped.representative_point()
        props = feature.get("properties") or {}
        event_id = props.get("LANDSLIDE_ID") or feature.get("id")
        title = props.get("LANDSLIDE_NAME") or props.get("LANDSLIDE_TYPE") or "Mapped landslide"
        date_value = props.get("LANDSLIDE_DATE")
        if date_value in (None, ""):
            date_value = props.get("LANDSLIDE_LIMIT_DATE")
        features.append({
            "type": "Feature",
            "id": event_id,
            "geometry": {"type": "Point", "coordinates": [round(point.x, 6), round(point.y, 6)]},
            "properties": {
                "id": event_id,
                "date": _arcgis_date(date_value),
                "title": title,
                "category": props.get("LANDSLIDE_TYPE"),
                "trigger": props.get("LANDSLIDE_TRIGGER_EVENT"),
                "size": None,
                "setting": props.get("LAND_USE"),
                # Polygon geometry is more informative than the representative point, but the
                # training contract accepts this conservative 1 km label accuracy class.
                "location_accuracy": "1km",
                "fatalities": None,
                "source_name": props.get("SOURCE_INFORMATION") or WASLID_SOURCE_NAME,
                "source_link": props.get("SOURCE_URL") or WASLID_LAYER_URL,
                "catalog": WASLID_SOURCE_NAME,
                "inventory_confidence": props.get("DATA_CONFIDENCE"),
                "source_layer": props.get("FEATURE_SOURCE"),
            },
        })
    return sorted(features, key=lambda feature: feature["properties"]["date"] or "")


def fetch_waslid(bbox, url: str = WASLID_QUERY_URL) -> dict:
    """Query the official Washington inventory for polygons intersecting the shared bbox."""
    params = {
        "where": "1=1",
        "geometry": ",".join(str(value) for value in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    try:
        response = requests.get(url, params=params, timeout=(15, 120))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"cannot query Washington landslide inventory: {type(exc).__name__}: {exc}") from exc


def write_landslides(features: list[dict], path: Path, bbox) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {len(features)} landslide points inside {list(bbox)} to {rel(path)}")


def stage_waslid(force: bool, pack: mp.Pack, paths: mp.PackPaths) -> None:
    """Use the official Washington inventory when the NASA export is unreachable."""
    if paths.landslides.exists() and not force:
        print(f"  {rel(paths.landslides)} exists, skipping (use --force to refresh)")
        return
    features = waslid_features(fetch_waslid(pack.bbox), pack.bbox)
    if not features:
        raise RuntimeError("Washington landslide inventory returned no features in the Rainier bbox")
    write_landslides(features, paths.landslides, pack.bbox)


def stage_landslides(force: bool, glc_source: str, pack: mp.Pack, paths: mp.PackPaths) -> None:
    """Prefer NASA GLC. Rainier supplements sparse high-accuracy labels with the official
    Washington inventory; every other pack keeps the GLC points alone, even none."""
    if paths.landslides.exists() and not force:
        print(f"  {rel(paths.landslides)} exists, skipping (use --force to refresh)")
        return
    rainier = pack.slug == mp.RAINIER_SLUG
    csv_path = GLC_CSV_PATH
    try:
        if urlparse(glc_source).scheme in ("http", "https"):
            # The cache holds the default export only, so another URL always downloads.
            if force or not GLC_CSV_PATH.exists() or glc_source != GLC_CSV_URL:
                print(f"  downloading {glc_source}")
                download(glc_source, GLC_CSV_PATH)
            csv_path = GLC_CSV_PATH
        else:
            csv_path = Path(glc_source)
        features = glc_features(csv_path, pack.bbox)
    except (OSError, RuntimeError, ValueError) as exc:
        if not rainier or urlparse(glc_source).scheme not in ("http", "https") or glc_source != GLC_CSV_URL:
            raise
        print(f"  NASA GLC unavailable ({type(exc).__name__}); using {WASLID_SOURCE_NAME}", file=sys.stderr)
        if csv_path == GLC_CSV_PATH:
            csv_path.unlink(missing_ok=True)  # never retain a partial/HTML response as a future cache
        return stage_waslid(force=True, pack=pack, paths=paths)
    if rainier:
        usable = usable_training_features(features)
        if len({(feature["geometry"]["coordinates"][0], feature["geometry"]["coordinates"][1])
                for feature in usable}) < 2:
            print(
                f"  NASA GLC supplied {len(features)} in-box events but only {len(usable)} usable "
                f"high-accuracy point; adding {WASLID_SOURCE_NAME} as a documented supplement",
                file=sys.stderr,
            )
            supplemental = waslid_features(fetch_waslid(pack.bbox), pack.bbox)
            if not supplemental:
                raise RuntimeError("NASA GLC is too sparse for spatial training and the supplemental inventory is empty")
            features = merge_catalog_features(features, supplemental)
    elif not features:
        print(f"  NASA GLC holds no events inside {list(pack.bbox)}; the historical record stays empty")
    write_landslides(features, paths.landslides, pack.bbox)


def main() -> int:
    """Run the selected stages. A failed stage is reported and does not stop the others."""
    parser = argparse.ArgumentParser(description="Download one mountain's DEM, land cover, and landslide points.")
    parser.add_argument("--mountain", default=mp.RAINIER_SLUG,
                        help=f"pack slug from mountain_packs.py (default: {mp.RAINIER_SLUG})")
    parser.add_argument("--only", default=",".join(STAGES), help="comma-separated stages (default: all three)")
    parser.add_argument("--force", action="store_true", help="download again even if an output exists")
    parser.add_argument(
        "--glc-csv",
        default=GLC_CSV_URL,
        metavar="URL_OR_PATH",
        help="NASA GLC export CSV to read, as a URL or local file; default URL falls back to the official Washington inventory",
    )
    args = parser.parse_args()
    pack, paths = mp.get(args.mountain), mp.paths(args.mountain)
    selected = [name.strip() for name in args.only.split(",") if name.strip()]
    unknown = sorted(set(selected) - set(STAGES))
    if unknown:
        parser.error(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")

    runners = {
        "dem": lambda: stage_dem(args.force, pack, paths),
        "landcover": lambda: stage_landcover(args.force, pack, paths),
        "landslides": lambda: stage_landslides(args.force, args.glc_csv, pack, paths),
    }
    failed = []
    for name in STAGES:
        if name not in selected:
            continue
        print(f"[{name}]")
        try:
            runners[name]()
        except Exception as exc:  # report and keep going so one blocked source does not stop the rest
            failed.append(name)
            print(f"  FAILED: {exc}", file=sys.stderr)
    if failed:
        print(f"Done with failures: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
