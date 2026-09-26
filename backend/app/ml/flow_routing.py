"""Debris-flow spreading over the terrain grid, strictly downhill (step 27).

Holmgren multiple-flow-direction routing: each cell passes its share of the flow
to every lower neighbor, weighted by (tan slope) ** exponent. Cells are handled
highest first, so a cell has all its inflow before it passes any on, and flow
only ever moves to a lower cell. A path stops where its travel angle from the
release falls below the reach angle or it passes the maximum runout.
"""

from __future__ import annotations

import heapq
import math

from app.ml.elevation import Grid

# Below this share of the released volume a cell is not part of the footprint.
MIN_SHARE = 0.002
RELEASE_RADIUS_M = 45

NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def spread(grid: Grid, lon: float, lat: float, exponent: float, reach_angle_deg: float, max_runout_m: float):
    """Share of the flow per cell and path distance from the release, as two arrays.

    Cells the flow never reaches have share 0 and distance inf. None when the
    release is off the grid.
    """
    import numpy as np

    heights = grid.heights
    rows, cols = heights.shape
    r0, c0 = grid.cell_of(lon, lat)
    if not (0 <= r0 < rows and 0 <= c0 < cols):
        return None
    cell = grid.cell_m(lat)
    top = heights[r0, c0]
    reach = math.tan(math.radians(reach_angle_deg))

    share = np.zeros(heights.shape)
    dist = np.full(heights.shape, np.inf)
    queue: list[tuple[float, int, int]] = []
    queued = np.zeros(heights.shape, dtype=bool)

    # The release is a small patch around the top of the route, never above it.
    radius = max(1, int(RELEASE_RADIUS_M / cell))
    patch = [
        (r, c)
        for r in range(r0 - radius, r0 + radius + 1)
        for c in range(c0 - radius, c0 + radius + 1)
        if 0 <= r < rows and 0 <= c < cols and math.hypot(r - r0, c - c0) <= radius and heights[r, c] <= top
    ]
    for r, c in patch:
        share[r, c] = 1 / len(patch)
        dist[r, c] = math.hypot(r - r0, c - c0) * cell
        heapq.heappush(queue, (-heights[r, c], r, c))
        queued[r, c] = True

    while queue:
        _, r, c = heapq.heappop(queue)
        here = share[r, c]
        if here < MIN_SHARE:
            continue
        z = heights[r, c]
        targets = []
        for dr, dc in NEIGHBORS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols):
                continue
            drop = z - heights[rr, cc]
            if drop <= 0:
                continue
            step = cell * (math.sqrt(2) if dr and dc else 1)
            travelled = dist[r, c] + step
            if travelled > max_runout_m or (top - heights[rr, cc]) < reach * travelled:
                continue
            targets.append((rr, cc, (drop / step) ** exponent, travelled))
        total = sum(weight for *_, weight, _ in targets)
        if total <= 0:
            continue  # A pit or the reach angle: the flow deposits here.
        for rr, cc, weight, travelled in targets:
            share[rr, cc] += here * weight / total
            dist[rr, cc] = min(dist[rr, cc], travelled)
            if not queued[rr, cc]:
                heapq.heappush(queue, (-heights[rr, cc], rr, cc))
                queued[rr, cc] = True
    return share, dist


# The body widens as it runs: one margin cell each side at the release, one more
# every MARGIN_EVERY_M of path, up to MAX_MARGIN cells. A margin cell is never
# higher than the cell it grows from, so the body spreads sideways and down, never up.
MAX_MARGIN = 4
MARGIN_EVERY_M = 300


def footprint(grid: Grid, share, dist):
    """The flow's cells with their arrival distance: the routed cells plus margins that widen downhill."""
    import numpy as np

    heights = grid.heights
    rows, cols = heights.shape
    cell = grid.cell_m(grid.lonlat(rows / 2, cols / 2)[1])
    inside = share >= MIN_SHARE
    arrive = np.where(inside, dist, np.inf)
    allowed = np.where(inside, np.minimum(MAX_MARGIN, 1 + dist // MARGIN_EVERY_M), 0)
    for ring in range(1, MAX_MARGIN + 1):
        grow = inside & (allowed >= ring)
        added = np.zeros_like(inside)
        for dr, dc in NEIGHBORS:
            src = _shift(grow, dr, dc)
            src_h = _shift(heights, dr, dc, fill=np.inf)
            src_d = _shift(arrive, dr, dc, fill=np.inf)
            src_a = _shift(allowed, dr, dc, fill=0)
            ok = src & ~inside & ~added & (heights <= src_h)
            arrive = np.where(ok, np.minimum(arrive, src_d + cell), arrive)
            allowed = np.where(ok, src_a, allowed)
            added |= ok
        inside = inside | added
    return inside, arrive


def shade_depth(mask, shades: int):
    """How many cells in from the edge each cell sits, capped at shades - 1. 0 is the edge."""
    import numpy as np

    depth = np.zeros(mask.shape, dtype=np.int8)
    current = mask.copy()
    for level in range(shades):
        depth[current] = level
        eroded = current.copy()
        for dr, dc in NEIGHBORS:
            eroded &= _shift(current, dr, dc, fill=False)
        current = eroded
        if not current.any():
            break
    return depth


def polygons(grid: Grid, mask, smooth_cells: float = 0.6) -> dict | None:
    """The mask as one GeoJSON Polygon or MultiPolygon in lon/lat, with the cell stairs rounded off."""
    import numpy as np
    from rasterio.features import shapes
    from shapely.geometry import mapping, shape
    from shapely.ops import transform, unary_union

    if not mask.any():
        return None
    rows, cols = np.nonzero(mask)
    r0, r1, c0, c1 = rows.min() - 1, rows.max() + 2, cols.min() - 1, cols.max() + 2
    r0, c0 = max(0, r0), max(0, c0)
    crop = mask[r0:r1, c0:c1].astype("uint8")
    parts = [shape(geom) for geom, value in shapes(crop, mask=crop > 0) if value]
    merged = unary_union(parts).buffer(smooth_cells, join_style=1).buffer(-smooth_cells, join_style=1).simplify(0.25)
    if merged.is_empty:
        return None
    lonlat = transform(lambda x, y, z=None: _to_lonlat(grid, x + c0, y + r0), merged)
    return mapping(lonlat)


def _to_lonlat(grid: Grid, xs, ys):
    import numpy as np

    pairs = [grid.lonlat(float(y), float(x)) for x, y in zip(np.atleast_1d(xs), np.atleast_1d(ys), strict=False)]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _shift(array, dr: int, dc: int, fill=False):
    """array moved so out[r, c] = array[r + dr, c + dc]; cells off the edge get fill."""
    import numpy as np

    out = np.full(array.shape, fill, dtype=array.dtype)
    rows, cols = array.shape
    out[max(0, -dr) : rows - max(0, dr), max(0, -dc) : cols - max(0, dc)] = array[
        max(0, dr) : rows - max(0, -dr), max(0, dc) : cols - max(0, -dc)
    ]
    return out
