"""The slopes most likely to fail (step 26).

Free of API and database imports, like hazard.py. With a probability raster this ranks
8-connected clusters at Moderate or above. This checkout often has no raster, so the
fallback ranks the mountain's own trails by grade (climb per kilometer). Seed lines start
at the lower end, so the release sits on the last coordinate.
"""

from __future__ import annotations

import math
from pathlib import Path

from app.config import REPO_ROOT
from app.risk import risk_level

MAX_PRESSURE_POINTS = 5
MIN_CLUSTER_KM2 = 0.05
SUPPRESS_M = 500
# 80 m of climb per km of trail sits on the Moderate/High boundary; 200 m/km is Extreme.
STEEP_MODERATE_M_PER_KM = 80.0
STEEP_HIGH_M_PER_KM = 200.0
# The worst route is scored on the 30 m grid, so sample its line about once a cell.
ROUTE_SAMPLE_M = 30

PROBABILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "probability.tif"
SUSCEPTIBILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def rank_pressure_points(trails: list[dict]) -> list[dict]:
    """Up to five JSON-ready pressure points, worst first.

    trails items: {id, name, coordinates: [[lon, lat], ...], length_km, elevation_gain_m}
    coordinates are WGS84 and start at the lower end.
    """
    raster = _raster_path()
    if raster is not None:
        try:
            ranked = _from_raster(raster, trails)
            if ranked:
                return ranked
        except Exception:
            # A missing band or an unreadable grid falls through to the trail grade.
            pass
    return _from_trails(trails)


def worst_route(trails: list[dict]) -> dict | None:
    """The one route the simulation runs on, as a pressure point. None without routes.

    With a probability raster, that is the route with the highest modeled chance anywhere
    along its line. Without one, it is the steepest route, the trail-grade ranking's first.
    """
    raster = _raster_path()
    if raster is not None:
        try:
            scored = _route_peaks(raster, trails)
        except Exception:
            # An unreadable grid falls through to the trail grade, like the ranking does.
            scored = []
        if scored:
            peak, trail = max(scored, key=lambda item: item[0])
            return _route_point(trail, peak)
    ranked = _from_trails(trails)
    return ranked[0] if ranked else None


def _route_peaks(path: Path, trails: list[dict]) -> list[tuple[float, dict]]:
    """The highest raster value along each route, sampled every ROUTE_SAMPLE_M."""
    import numpy as np
    import rasterio
    from rasterio.warp import transform

    scored: list[tuple[float, dict]] = []
    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        if src.nodata is not None:
            values[values == src.nodata] = np.nan
        height, width = values.shape
        for trail in trails:
            points = _densify(_line(trail), ROUTE_SAMPLE_M)
            if len(points) < 2:
                continue
            xs, ys = transform("EPSG:4326", src.crs, [p[0] for p in points], [p[1] for p in points])
            rows, cols = rasterio.transform.rowcol(src.transform, xs, ys)
            picked = [
                float(values[row, col])
                for row, col in zip(rows, cols, strict=False)
                if 0 <= row < height and 0 <= col < width and np.isfinite(values[row, col])
            ]
            if picked:
                scored.append((max(picked), trail))
    return scored


def _route_point(trail: dict, peak: float) -> dict:
    coords = _line(trail)
    release = coords[-1]
    length_mi = (float(trail.get("length_km") or 0) or _length_m(coords) / 1000) * 0.621371
    return {
        "id": f"route-{trail['id']}",
        "rank": 1,
        "level": risk_level(peak),
        "peak": round(peak, 2),
        "lon": release[0],
        "lat": release[1],
        "polygon": _triangle(release[0], release[1], 40),
        "facing": _compass(_bearing(release, coords[-2])),
        "elevation_m": None,
        "drivers": ["Modeled probability"],
        "trail_id": str(trail["id"]),
        "trail_name": trail.get("name"),
        "start_mile": None,
        "end_mile": round(length_mi, 2),
    }


def _densify(coords: list[list[float]], step_m: float) -> list[list[float]]:
    if len(coords) < 2:
        return coords
    out = [coords[0]]
    for start, end in zip(coords, coords[1:], strict=False):
        pieces = max(1, int(_haversine((start[0], start[1]), (end[0], end[1])) // step_m))
        for index in range(1, pieces + 1):
            frac = index / pieces
            out.append([start[0] + (end[0] - start[0]) * frac, start[1] + (end[1] - start[1]) * frac])
    return out


def peak_for_steepness(meters_per_km: float) -> float:
    """Map trail grade onto the shared 0–1 bins. 80 m/km → 0.45, 200 m/km → 0.75."""
    span = STEEP_HIGH_M_PER_KM - STEEP_MODERATE_M_PER_KM
    peak = 0.45 + (meters_per_km - STEEP_MODERATE_M_PER_KM) * (0.30 / span)
    return max(0.22, min(0.92, peak))


def _from_trails(trails: list[dict]) -> list[dict]:
    ranked: list[tuple[float, dict]] = []
    for trail in trails:
        coords = _line(trail)
        if len(coords) < 2:
            continue
        length_km = float(trail.get("length_km") or 0) or _length_m(coords) / 1000
        gain = float(trail.get("elevation_gain_m") or 0)
        steepness = gain / max(length_km, 0.05)
        ranked.append((steepness, trail))
    ranked.sort(key=lambda item: item[0], reverse=True)

    points: list[dict] = []
    for steepness, trail in ranked[:MAX_PRESSURE_POINTS]:
        coords = _line(trail)
        release = coords[-1]
        downhill = coords[-2]
        peak = peak_for_steepness(steepness)
        length_mi = (float(trail.get("length_km") or 0) or _length_m(coords) / 1000) * 0.621371
        # The upper quarter of the tread is the stretch the release sits on.
        start_mile = round(length_mi * 0.75, 2)
        end_mile = round(length_mi, 2)
        drivers = ["Steep slopes"]
        if steepness >= 150:
            drivers.append("Drainage channel")
        points.append(
            {
                "id": f"trail-{trail['id']}",
                "rank": len(points) + 1,
                "level": risk_level(peak),
                "peak": round(peak, 2),
                "lon": release[0],
                "lat": release[1],
                "polygon": _triangle(release[0], release[1], 40),
                "facing": _compass(_bearing(release, downhill)),
                "elevation_m": None,
                "drivers": drivers,
                "trail_id": str(trail["id"]),
                "trail_name": trail.get("name"),
                "start_mile": start_mile,
                "end_mile": end_mile,
            }
        )
    return points


def _from_raster(path: Path, trails: list[dict]) -> list[dict]:
    """Clusters on a probability or susceptibility grid. Used when the GeoTIFF is present."""
    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform

    from pyproj import Transformer

    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        if src.nodata is not None:
            values[values == src.nodata] = np.nan
        mask = np.isfinite(values) & (values >= 0.2)
        if not mask.any():
            return []
        labeled = _label(mask)
        transformer = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
        clusters: list[tuple[float, dict]] = []
        for geom, value in shapes(labeled, mask=labeled > 0, transform=src.transform):
            label = int(value)
            cells = labeled == label
            area_km2 = float(cells.sum()) * abs(src.res[0] * src.res[1]) / 1_000_000
            if area_km2 < MIN_CLUSTER_KM2:
                continue
            peak = float(np.nanmax(values[cells]))
            score = peak * area_km2
            polygon = shape(geom)
            centroid = polygon.centroid
            lon, lat = transformer.transform(centroid.x, centroid.y)
            outline = shp_transform(lambda x, y, z=None: transformer.transform(x, y), polygon.simplify(30))
            clusters.append(
                (
                    score,
                    {
                        "peak": round(peak, 2),
                        "level": risk_level(peak),
                        "lon": lon,
                        "lat": lat,
                        "polygon": outline.__geo_interface__,
                        "area_km2": area_km2,
                    },
                )
            )
    clusters.sort(key=lambda item: item[0], reverse=True)
    kept: list[dict] = []
    for _score, cluster in clusters:
        if any(_haversine((cluster["lon"], cluster["lat"]), (other["lon"], other["lat"])) < SUPPRESS_M for other in kept):
            continue
        trail = _nearest_trail(cluster["lon"], cluster["lat"], trails)
        kept.append(
            {
                "id": f"cluster-{len(kept) + 1}",
                "rank": len(kept) + 1,
                "level": cluster["level"],
                "peak": cluster["peak"],
                "lon": cluster["lon"],
                "lat": cluster["lat"],
                "polygon": cluster["polygon"],
                "facing": "S",
                "elevation_m": None,
                "drivers": ["Steep slopes"],
                "trail_id": None if trail is None else str(trail["id"]),
                "trail_name": None if trail is None else trail.get("name"),
                "start_mile": None,
                "end_mile": None,
            }
        )
        if len(kept) == MAX_PRESSURE_POINTS:
            break
    return kept


def _label(mask) -> "object":
    """8-connected component labels, 0 on the background."""
    import numpy as np

    height, width = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int32)
    current = 0
    for row in range(height):
        for col in range(width):
            if not mask[row, col] or labels[row, col]:
                continue
            current += 1
            stack = [(row, col)]
            labels[row, col] = current
            while stack:
                r, c = stack.pop()
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < height and 0 <= cc < width and mask[rr, cc] and labels[rr, cc] == 0:
                            labels[rr, cc] = current
                            stack.append((rr, cc))
    return labels


def _raster_path() -> Path | None:
    for path in (PROBABILITY_PATH, SUSCEPTIBILITY_PATH):
        if path.exists():
            return path
    return None


def _line(trail: dict) -> list[list[float]]:
    coords = trail.get("coordinates") or []
    return [list(pair) for pair in coords if isinstance(pair, (list, tuple)) and len(pair) >= 2]


def _nearest_trail(lon: float, lat: float, trails: list[dict]) -> dict | None:
    best: tuple[float, dict] | None = None
    for trail in trails:
        coords = _line(trail)
        if len(coords) < 2:
            continue
        upper = coords[-1]
        distance = _haversine((lon, lat), (upper[0], upper[1]))
        if distance > 0.5 * 1609.344:
            continue
        if best is None or distance < best[0]:
            best = (distance, trail)
    return None if best is None else best[1]


def _triangle(lon: float, lat: float, radius_m: float) -> dict:
    ring = [_move(lon, lat, bearing, radius_m) for bearing in (0, 120, 240)]
    closed = [[point[0], point[1]] for point in ring]
    closed.append(closed[0])
    return {"type": "Polygon", "coordinates": [closed]}


def _compass(bearing: float) -> str:
    return COMPASS[int((bearing + 22.5) // 45) % 8]


def _bearing(a: list[float], b: list[float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _move(lon: float, lat: float, bearing: float, meters: float) -> tuple[float, float]:
    radius = 6378137.0
    br = math.radians(bearing)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(meters / radius) + math.cos(lat1) * math.sin(meters / radius) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(meters / radius) * math.cos(lat1),
        math.cos(meters / radius) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lon2), math.degrees(lat2)


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6378137.0 * math.asin(min(1.0, math.sqrt(h)))


def _length_m(coords: list[list[float]]) -> float:
    return sum(_haversine((a[0], a[1]), (b[0], b[1])) for a, b in zip(coords, coords[1:], strict=False))
