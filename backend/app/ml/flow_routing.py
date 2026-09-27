"""The runout spreading over the terrain grid, strictly downhill (step 27).

Tier A of context/docs/LANDSLIDE_SIMULATION.md, with Tier B's speed carried along. Each
cell passes its share of the flow to its lower neighbors, weighted by Holmgren's slope term
times a persistence term for the direction the flow came in. Cells are handled highest
first, so a cell has all its inflow before it passes any on, and flow only ever moves to a
lower cell (a project rule on top of Flow-Py, whose remap would let it climb).

A Flow-Py energy line runs with the flow: each move gains its drop, loses tan(alpha) per
metre, and is capped at V_max^2 / 2g. A move is made only while that head stays positive,
the process's sled still has speed, and the path is under the maximum runout. Arrival time
is the sum of step lengths over the mean speed at their ends. See runout_physics.py.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.ml import runout_physics as physics
from app.ml.elevation import Grid

# Below this share of the released volume a cell is not part of the footprint. It is also the
# routing cutoff, R_stop, so no sub-threshold trickle can re-form a detached patch downslope.
MIN_SHARE = 0.002
RELEASE_RADIUS_M = 45

NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass
class Routed:
    """Per-cell results of one spread. Cells the flow never reaches: share 0, the rest inf or 0."""

    share: object  # fraction of the release through the cell
    dist: object  # shortest horizontal path distance from the release, m
    arrival: object  # first arrival of the front, s
    speed: object  # fastest front speed through the cell, m/s
    head: object  # largest energy-line head Z_delta, m


def spread(
    grid: Grid,
    lon: float,
    lat: float,
    process: physics.FlowProcess,
    reach_angle_deg: float,
    max_runout_m: float,
) -> Routed | None:
    """Route the flow from a release patch at (lon, lat). None when the release is off the grid."""
    import numpy as np

    heights = grid.heights
    rows, cols = heights.shape
    r0, c0 = grid.cell_of(lon, lat)
    if not (0 <= r0 < rows and 0 <= c0 < cols):
        return None
    cell = grid.cell_m(lat)
    top = heights[r0, c0]
    tan_alpha = math.tan(math.radians(reach_angle_deg))
    cap = process.z_delta_max_m

    share = np.zeros(heights.shape)
    dist = np.full(heights.shape, np.inf)
    arrival = np.full(heights.shape, np.inf)
    speed = np.zeros(heights.shape)
    head = np.zeros(heights.shape)
    # Flux-weighted sum of the directions flow came in by, for persistence.
    come_r = np.zeros(heights.shape)
    come_c = np.zeros(heights.shape)
    # The slope of the move that set each cell's speed, for PCM's correction at a slope break.
    slope_in = np.full(heights.shape, np.nan)
    queue: list[tuple[float, int, int]] = []
    queued = np.zeros(heights.shape, dtype=bool)

    # The release is a small patch around the top of the route, never above it, set off from
    # rest. Its cells start on the energy line drawn from the top.
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
        arrival[r, c] = 0.0
        head[r, c] = max(0.0, min(cap, (top - heights[r, c]) - tan_alpha * dist[r, c]))
        heapq.heappush(queue, (-heights[r, c], r, c))
        queued[r, c] = True

    while queue:
        _, r, c = heapq.heappop(queue)
        here = share[r, c]
        if here < MIN_SHARE:
            continue
        z = heights[r, c]
        norm = math.hypot(come_r[r, c], come_c[r, c])
        moves = []
        for dr, dc in NEIGHBORS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols):
                continue
            drop = z - heights[rr, cc]
            if drop <= 0:
                continue
            step = cell * (math.sqrt(2) if dr and dc else 1)
            travelled = dist[r, c] + step
            if travelled > max_runout_m:
                continue
            reach_head = physics.energy_head(head[r, c], drop, step, tan_alpha, cap)
            if reach_head <= 0:
                continue  # Past the energy line: the flow deposits before this cell.
            v = _speed(process, speed[r, c], slope_in[r, c], drop, step, reach_head)
            if v <= 0:
                continue  # The sled has stopped.
            cos_turn = None if norm == 0 else (come_r[r, c] * dr + come_c[r, c] * dc) / (norm * math.hypot(dr, dc))
            terrain = physics.terrain_weight(drop, step, process)
            weight = terrain * physics.persistence_weight(cos_turn, process.persistence)
            moves.append((rr, cc, dr, dc, drop, step, travelled, reach_head, v, terrain, weight))
        if not moves:
            continue  # A pit, the energy line, or a stopped sled: the flow deposits here.
        total = sum(move[10] for move in moves)
        # Every way on is a sharp turn: the flow bends with the terrain rather than stopping
        # mid-slope, and the energy line still decides where it stops.
        use = 10 if total > 0 else 9
        total = total if total > 0 else sum(move[9] for move in moves)
        for move in moves:
            rr, cc, dr, dc, drop, step, travelled, reach_head, v, *_ = move
            passed = here * move[use] / total
            share[rr, cc] += passed
            length = math.hypot(step, drop)
            dist[rr, cc] = min(dist[rr, cc], travelled)
            arrival[rr, cc] = min(arrival[rr, cc], arrival[r, c] + physics.step_seconds(length, speed[r, c], v))
            if v > speed[rr, cc]:
                speed[rr, cc] = v
                slope_in[rr, cc] = math.atan2(drop, step)
            head[rr, cc] = max(head[rr, cc], reach_head)
            come_r[rr, cc] += passed * dr / math.hypot(dr, dc)
            come_c[rr, cc] += passed * dc / math.hypot(dr, dc)
            if not queued[rr, cc]:
                heapq.heappush(queue, (-heights[rr, cc], rr, cc))
                queued[rr, cc] = True
    return Routed(share=share, dist=dist, arrival=arrival, speed=speed, head=head)


def _speed(process: physics.FlowProcess, v_from: float, slope_from: float, drop: float, step: float, head_m: float) -> float:
    """The front's speed on arriving at the next cell (Tier B).

    A debris flow runs at the energy-line speed, which the cap already holds under V_max
    (Flow-R's simplified friction-limited model). A snow avalanche runs as a Voellmy sled,
    with PCM's slowdown at a slope break, and never faster than its own energy line allows,
    so the front decelerates into the alpha-beta stop instead of halting at full speed.
    """
    energy = physics.head_speed(head_m)
    if not process.voellmy:
        return energy
    slope_out = math.atan2(drop, step)
    v0 = v_from * physics.slope_turn_factor(None if math.isnan(slope_from) else slope_from, slope_out)
    v_sq = physics.pcm_speed_sq(v0 * v0, drop, step, process.mu, process.xi_ms2, process.flow_height_m)
    if v_sq <= 0:
        return 0.0
    return min(math.sqrt(v_sq), energy)


def steepest_profile(grid: Grid, lon: float, lat: float, max_runout_m: float) -> list[tuple[float, float]]:
    """(horizontal distance, height) down the steepest descent from (lon, lat), for alpha-beta.

    The single-flow-direction path (D8, section 4.1): each step goes to the neighbor with the
    steepest drop, and the path ends at a pit, the grid's edge, or the maximum runout.
    """
    heights = grid.heights
    rows, cols = heights.shape
    r, c = grid.cell_of(lon, lat)
    if not (0 <= r < rows and 0 <= c < cols):
        return []
    cell = grid.cell_m(lat)
    s = 0.0
    profile = [(0.0, float(heights[r, c]))]
    while True:
        best = None
        for dr, dc in NEIGHBORS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols):
                continue
            step = cell * (math.sqrt(2) if dr and dc else 1)
            gradient = (heights[r, c] - heights[rr, cc]) / step
            if gradient > 0 and (best is None or gradient > best[0]):
                best = (gradient, rr, cc, step)
        if best is None or s + best[3] > max_runout_m:
            return profile
        _, r, c, step = best
        s += step
        profile.append((s, float(heights[r, c])))


# The body widens as it runs: one margin cell each side at the release, one more
# every MARGIN_EVERY_M of path, up to MAX_MARGIN cells. A margin cell is never
# higher than the cell it grows from, so the body spreads sideways and down, never up.
MAX_MARGIN = 4
MARGIN_EVERY_M = 300


def footprint(grid: Grid, routed: Routed):
    """The flow's cells, their path distance, and their arrival time.

    The routed cells plus margins that widen downhill. A margin cell is display, not physics:
    it takes the arrival time of the cell it grows from, so the front comes down with its
    full width, and one more cell of distance.
    """
    import numpy as np

    heights = grid.heights
    rows, cols = heights.shape
    cell = grid.cell_m(grid.lonlat(rows / 2, cols / 2)[1])
    inside = routed.share >= MIN_SHARE
    arrive = np.where(inside, routed.dist, np.inf)
    when = np.where(inside, routed.arrival, np.inf)
    allowed = np.where(inside, np.minimum(MAX_MARGIN, 1 + routed.dist // MARGIN_EVERY_M), 0)
    for ring in range(1, MAX_MARGIN + 1):
        grow = inside & (allowed >= ring)
        added = np.zeros_like(inside)
        for dr, dc in NEIGHBORS:
            src = _shift(grow, dr, dc)
            src_h = _shift(heights, dr, dc, fill=np.inf)
            src_d = _shift(arrive, dr, dc, fill=np.inf)
            src_t = _shift(when, dr, dc, fill=np.inf)
            src_a = _shift(allowed, dr, dc, fill=0)
            ok = src & ~inside & ~added & (heights <= src_h)
            arrive = np.where(ok, np.minimum(arrive, src_d + cell), arrive)
            when = np.where(ok, np.minimum(when, src_t), when)
            allowed = np.where(ok, src_a, allowed)
            added |= ok
        inside = inside | added
    return inside, arrive, when


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
