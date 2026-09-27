"""An illustrative runout from the route most likely to fail (step 27).

No model call. The process follows the place: a mountain's runout is a snow avalanche and a
hill's is a debris flow (runout_physics.py, after context/docs/LANDSLIDE_SIMULATION.md).

On the terrain grid, flow_routing.py spreads it strictly downhill from the route's highest
point: Holmgren weights with persistence for where it goes, an energy line for where it
stops (11 degrees for a debris flow, the alpha-beta angle for snow, capped at V_max), and
the process's speed model for when it gets there. Without that grid, the flow follows the
source route: it releases at the route's highest point on the terrain tiles and walks the
line only while every next sample is no higher than the last, so it never flows uphill,
under the same energy line and speed. When no terrain tile can be read, it falls back to
the seed convention (lines start at the lower end) and a constant FRONT_SPEED_MS. Either way
the frames grow from the release toward the valley.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from app.ml import flow_field, flow_routing
from app.ml import runout_physics as physics
from app.ml.elevation import height_grid, sample_elevations
from app.ml.pressure import _bearing, _haversine, _line, _move

MAX_RUNOUT_M = 6000
# Only when no terrain can be read: arrival time = path distance / this.
FRONT_SPEED_MS = 5
MAX_FRAMES = 40
# One frame per this much runout, 8 to 40 frames, so a longer runout plays longer.
FRAME_EVERY_M = 75
CHANNEL_M = 100
SAMPLE_M = 80

METHOD_TRAIL = "Illustrative runout along the trail's downhill line. Not a forecast of timing."

M_PER_MI = 1609.344


def method_dem(process: physics.FlowProcess, cell_m: float, reach_angle_deg: float) -> str:
    """The method line for a runout spread over the terrain grid. It names the model it used."""
    if process.voellmy:
        model = f"α–β reach angle {reach_angle_deg:.0f}°, Voellmy sled (μ {process.mu:g}, ξ {process.xi_ms2:g} m/s²)"
    else:
        model = f"energy line at {reach_angle_deg:.0f}°, speed capped at {process.v_max_ms:g} m/s"
    return f"Illustrative {process.label} runout on {cell_m:.0f} m terrain: {model}. Not a forecast of timing."


def method_trail_terrain(process: physics.FlowProcess) -> str:
    return (
        f"Illustrative {process.label} runout from the route's highest point, downhill along the trail. "
        "Not a forecast of timing."
    )


def trace_runout(point: dict, trails: list[dict], process: physics.FlowProcess = physics.DEBRIS_FLOW) -> dict:
    """Frames and steps for one pressure point. JSON-ready. Never calls a model."""
    terrain = _over_terrain(point, trails, process)
    if terrain is not None:
        return terrain
    return _along_trail(point, trails, process)


def _over_terrain(point: dict, trails: list[dict], process: physics.FlowProcess) -> dict | None:
    """The flow spread over the terrain grid from the top of the source route. None without terrain."""
    import numpy as np

    trail = _source_trail(point, trails)
    coords = _line(trail) if trail else []
    top = _route_top(coords)
    if top is None:
        return None
    lon, lat, top_m = top
    grid = height_grid(lon, lat, MAX_RUNOUT_M)
    if grid is None:
        return None
    reach = _reach_angle(process, flow_routing.steepest_profile(grid, lon, lat, MAX_RUNOUT_M))
    if reach is None:
        return None
    alpha, beta, beta_found = reach
    routed = flow_routing.spread(grid, lon, lat, process, alpha, MAX_RUNOUT_M)
    if routed is None:
        return None
    mask, arrive, when = flow_routing.footprint(grid, routed)
    moved = (routed.share >= flow_routing.MIN_SHARE) & (routed.dist > flow_routing.RELEASE_RADIUS_M)
    if mask.sum() < 3 or not moved.any() or not np.isfinite(when[mask]).all():
        # Released on ground gentler than the reach angle, the flow never leaves its patch.
        # The trail walk below still shows where the route itself runs downhill.
        return None
    heights = grid.heights
    total = float(arrive[mask].max())
    duration = float(when[mask].max())
    level = point.get("level") or "high"
    release_level = level if level in RAMP else "high"

    frame_count = min(MAX_FRAMES, max(8, int(total / FRAME_EVERY_M)))
    frames = []
    for index in range(frame_count):
        t_s = duration * (index + 1) / frame_count
        visible = mask & (when <= t_s + 1e-6)
        depth = flow_routing.shade_depth(visible, SHADES)
        deepest = max(1, int(depth.max()))
        features = []
        for shade in reversed(range(SHADES)):
            # The deepest cells are the dark core and the edge is the palest band. Each band
            # is every cell at least that far in, so the bands nest.
            need = math.ceil((SHADES - 1 - shade) * deepest / (SHADES - 1))
            geometry = flow_routing.polygons(grid, visible & (depth >= need))
            if geometry is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {"level": release_level, "intensity": INTENSITY[release_level], "shade": shade, "rim": shade == SHADES - 1},
                    "geometry": geometry,
                }
            )
        frames.append({"index": index, "t_s": round(t_s, 1), "geojson": {"type": "FeatureCollection", "features": features}})

    # The centerline for the steps: the cell carrying the most flow in each distance band.
    line = [(lon, lat, 0.0, 0.0)] + [sample for sample in _centerline(grid, routed.share, mask, arrive, when) if sample[2] > 0]
    stop_row, stop_col = np.unravel_index(np.argmax(np.where(mask, arrive, -1)), mask.shape)
    stop_lon, stop_lat = grid.lonlat(stop_row + 0.5, stop_col + 0.5)
    line.append((stop_lon, stop_lat, total, duration))
    samples = [(x, y, d) for x, y, d, _ in line]
    clock = _clock_from([(d, t) for *_, d, t in line])
    drop_m = top_m - float(heights[stop_row, stop_col])
    steps = _steps(point, trail, trails, samples, drop_m, _covered_miles(trail, grid, mask), clock)
    cell_m = grid.cell_m(lat)
    return {
        "method": method_dem(process, cell_m, alpha),
        "source": "dem",
        "release": {"lon": lon, "lat": lat, "elevation_m": round(top_m, 1)},
        "duration_s": round(duration, 1),
        "distance_m": round(total, 1),
        "drop_m": round(drop_m, 1),
        "frames": frames,
        "field": flow_field.terrain_field(grid, mask, when, routed.share, duration),
        "steps": steps,
        "physics": _physics_summary(process, alpha, beta, beta_found, float(routed.speed[mask].max()), cell_m),
    }


def _reach_angle(process: physics.FlowProcess, profile: list[tuple[float, float]]) -> tuple[float, float | None, bool | None] | None:
    """(alpha, beta, beta point found). A fixed-angle process has no beta. None when snow has no profile."""
    if process.reach_angle_deg is not None:
        return process.reach_angle_deg, None, None
    if len(profile) < 2:
        return None
    return physics.alpha_beta(profile)


def _physics_summary(
    process: physics.FlowProcess,
    alpha: float,
    beta: float | None,
    beta_found: bool | None,
    peak_speed: float,
    cell_m: float,
) -> dict:
    """The parameter set and the Tier B results, JSON-ready, so the run shows what it assumed."""
    return {
        "process": process.name,
        "model": process.citation,
        "reach_angle_deg": round(alpha, 1),
        "beta_deg": None if beta is None else round(beta, 1),
        "beta_point_found": beta_found,
        "holmgren_exponent": process.holmgren_exponent,
        "persistence": "cosine" if process.persistence == physics.PERSISTENCE_COSINE else "proportional",
        "v_max_ms": process.v_max_ms,
        "mu": process.mu,
        "xi_ms2": process.xi_ms2,
        "flow_height_m": process.flow_height_m,
        "peak_speed_ms": round(peak_speed, 1),
        "cell_m": round(cell_m, 1),
    }


def _clock_from(pairs: list[tuple[float, float]]) -> Callable[[float], float]:
    """Seconds at a distance down the path, linear between (distance, seconds) pairs and never going back."""
    import numpy as np

    ordered = sorted(pairs)
    dists = np.array([d for d, _ in ordered], dtype="float64")
    times = np.maximum.accumulate(np.array([t for _, t in ordered], dtype="float64"))
    return lambda dist: float(np.interp(dist, dists, times))


def _route_top(coords: list[list[float]]) -> tuple[float, float, float] | None:
    """The highest point on the route, sampled every SAMPLE_M. None without terrain."""
    line = _sample(coords, SAMPLE_M, limit_m=math.inf) if len(coords) >= 2 else []
    if not line:
        return None
    heights = sample_elevations([(lon, lat) for lon, lat, _ in line])
    if heights is None:
        return None
    index = max(range(len(line)), key=lambda i: heights[i])
    return line[index][0], line[index][1], heights[index]


def _centerline(grid, share, mask, arrive, when) -> list[tuple[float, float, float, float]]:
    """(lon, lat, metres, seconds) at the cell carrying the most flow in each SAMPLE_M band."""
    import numpy as np

    routed = mask & (share >= flow_routing.MIN_SHARE)
    bands = (np.where(routed, arrive, -SAMPLE_M) // SAMPLE_M).astype(int)
    out = []
    for band in range(int(bands.max()) + 1):
        cells = np.nonzero(bands == band)
        if not len(cells[0]):
            continue
        best = int(np.argmax(share[cells]))
        r, c = cells[0][best], cells[1][best]
        lon, lat = grid.lonlat(r + 0.5, c + 0.5)
        out.append((lon, lat, float(arrive[r, c]), float(when[r, c])))
    return out


def _covered_miles(trail: dict | None, grid, mask) -> tuple[float, float] | None:
    """The source route's mile range inside the footprint, in the line's own mileage. None if it misses."""
    coords = _line(trail) if trail else []
    if len(coords) < 2:
        return None
    rows, cols = mask.shape
    hit = []
    for lon, lat, along in _sample(coords, 20, limit_m=math.inf):
        r, c = grid.cell_of(lon, lat)
        if 0 <= r < rows and 0 <= c < cols and mask[r, c]:
            hit.append(along / M_PER_MI)
    return (min(hit), max(hit)) if hit else None


def _along_trail(point: dict, trails: list[dict], process: physics.FlowProcess) -> dict:
    trail = _source_trail(point, trails)
    coords = _line(trail) if trail else []
    if len(coords) < 2:
        coords = [
            [point["lon"], point["lat"]],
            _move(point["lon"], point["lat"], 180, 400),
        ]
        coords = [list(pair) for pair in coords]
    trail_len = _haversine_line(coords)
    downhill = _downhill(coords)
    summary = None
    clock: Callable[[float], float] = lambda dist: dist / FRONT_SPEED_MS
    if downhill is not None:
        samples, heights, (release_mi, end_mi) = downhill
        walked = _run_profile(samples, heights, process)
        if walked is not None:
            samples, heights, clock, summary = walked
            # The energy line may stop the walk early: the covered miles end where it does.
            end_mi = release_mi + math.copysign(samples[-1][2] / M_PER_MI, end_mi - release_mi)
        miles = (min(release_mi, end_mi), max(release_mi, end_mi))
        method = method_trail_terrain(process)
        drop_m = heights[0] - heights[-1]
        release = {"lon": samples[0][0], "lat": samples[0][1], "elevation_m": round(heights[0], 1)}
    else:
        # No terrain: lower end first in the seed, so reversing walks the failure downhill.
        reverse = list(reversed(coords))
        samples = _sample(reverse, SAMPLE_M)
        if len(samples) < 2:
            samples = [(reverse[0][0], reverse[0][1], 0.0), (reverse[-1][0], reverse[-1][1], _haversine(tuple(reverse[0]), tuple(reverse[-1])))]
        gain = float((trail or {}).get("elevation_gain_m") or 0)
        on_trail = min(samples[-1][2], trail_len or samples[-1][2])
        drop_m = gain * (on_trail / trail_len) if trail_len else 0.0
        length_mi = _trail_miles(trail, samples)
        miles = (max(0.0, length_mi - on_trail / M_PER_MI), length_mi)
        method = METHOD_TRAIL
        release = {"lon": samples[0][0], "lat": samples[0][1], "elevation_m": None}

    total = samples[-1][2]
    frame_count = min(MAX_FRAMES, max(8, int(total / FRAME_EVERY_M)))
    frame_count = min(frame_count, max(2, len(samples) - 1))
    # Each frame ends a little further down the line than the one before, so none shrinks.
    frames = _growing(frame_count, samples, point.get("level") or "high", clock)

    steps = _steps(point, trail, trails, samples, drop_m, miles, clock)
    duration = clock(total)
    return {
        "method": method,
        "source": "trail",
        "release": release,
        "duration_s": round(duration, 1),
        "distance_m": round(total, 1),
        "drop_m": round(drop_m, 1),
        "frames": frames,
        "field": flow_field.trail_field(samples, _half_width, clock, duration),
        "steps": steps,
        "physics": summary,
    }


def _run_profile(
    samples: list[tuple[float, float, float]],
    heights: list[float],
    process: physics.FlowProcess,
) -> tuple[list[tuple[float, float, float]], list[float], Callable[[float], float], dict] | None:
    """The downhill walk under the process's energy line and speed. None if it cannot leave the release.

    The same Tier A stop and Tier B speed as the terrain grid, one sample at a time: the walk
    ends where the energy-line head or the sled's speed runs out.
    """
    reach = _reach_angle(process, [(d, z) for (_, _, d), z in zip(samples, heights, strict=True)])
    if reach is None:
        return None
    alpha, beta, beta_found = reach
    tan_alpha = math.tan(math.radians(alpha))
    head, speed, slope_in, t, peak = 0.0, 0.0, None, 0.0, 0.0
    times = [0.0]
    for i in range(1, len(samples)):
        drop = heights[i - 1] - heights[i]
        step = samples[i][2] - samples[i - 1][2]
        next_head = physics.energy_head(head, drop, step, tan_alpha, process.z_delta_max_m)
        if next_head <= 0 or step <= 0:
            break
        v = flow_routing._speed(process, speed, math.nan if slope_in is None else slope_in, drop, step, next_head)
        if v <= 0:
            break
        t += physics.step_seconds(math.hypot(step, drop), speed, v)
        head, speed, slope_in = next_head, v, math.atan2(drop, step)
        times.append(t)
        peak = max(peak, v)
    if len(times) < 2:
        return None
    kept = len(times)
    summary = _physics_summary(process, alpha, beta, beta_found, peak, SAMPLE_M)
    walked = samples[:kept]
    return walked, heights[:kept], _clock_from([(d, t) for (_, _, d), t in zip(walked, times, strict=True)]), summary


RAMP = ("moderate", "high", "extreme")
# The footprint is drawn as SHADES nested bands, dark dirt at the core to pale at the edge.
SHADES = 5
CORE_WIDTH_M = 24
# Same stepped opacities as the raster heat map: amber 0.40, orange 0.55, red 0.70.
INTENSITY = {"moderate": 0.40, "high": 0.55, "extreme": 0.70}


def _growing(count: int, samples: list[tuple[float, float, float]], level: str, clock: Callable[[float], float]) -> list[dict]:
    """count frames, each corridor holding every sample of the one before it and one more."""
    out = []
    prev = 1
    for index in range(count):
        last = max(prev + 1, int(round((index + 1) / count * (len(samples) - 1))) + 1)
        last = min(len(samples), last)
        prev = last - 1
        chunk = samples[:last]
        out.append(
            {
                "index": index,
                "t_s": round(clock(chunk[-1][2]), 1),
                "geojson": {"type": "FeatureCollection", "features": _corridor(chunk, level)},
            }
        )
    return out


def _corridor(samples: list[tuple[float, float, float]], level: str) -> list[dict]:
    """The footprint as nested bands, the full edge first and the dark core last.

    Shade 0 is the core: a narrow strip of dark dirt that follows the path. Each
    band out is wider and lighter, and the outer bands fan out as the flow
    descends, so the flow starts brown at the release and pales toward its sides.
    Every band carries the release level for the contract; color comes from shade.
    """
    release = level if level in RAMP else "high"
    features = []
    for shade in reversed(range(SHADES)):
        features.append(_band(samples, shade, release, INTENSITY[release], rim=shade == SHADES - 1))
    return features


def _band(samples: list[tuple[float, float, float]], shade: int, level: str, intensity: float, rim: bool = False) -> dict:
    left: list[list[float]] = []
    right: list[list[float]] = []
    for index, (lon, lat, dist) in enumerate(samples):
        nxt = samples[min(index + 1, len(samples) - 1)]
        prv = samples[max(index - 1, 0)]
        heading = _bearing([prv[0], prv[1]], [nxt[0], nxt[1]]) if nxt != prv else 180
        full = 2 * _half_width(dist)
        core = min(CORE_WIDTH_M, full)
        half = (core + (full - core) * shade / (SHADES - 1)) / 2
        lo = _move(lon, lat, (heading - 90) % 360, half)
        ro = _move(lon, lat, (heading + 90) % 360, half)
        left.append([lo[0], lo[1]])
        right.append([ro[0], ro[1]])
    ring = left + list(reversed(right))
    ring.append(ring[0])
    return {
        "type": "Feature",
        "properties": {"level": level, "intensity": intensity, "shade": shade, "rim": rim},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _half_width(dist: float) -> float:
    """Half the corridor's full width at this distance down the path: it fans out as it descends."""
    return (40 + min(180, dist * 0.045)) / 2


def _downhill(coords: list[list[float]]) -> tuple[list[tuple[float, float, float]], list[float], tuple[float, float]] | None:
    """The route from its highest point, walked only while it keeps going down. None without terrain.

    Samples the whole line, releases at the highest sample, then takes whichever way
    along the line drops further. The walk stops at the first sample higher than the
    one before it, so heights never rise from release to stop. Also returns the miles of
    the release and of the walk's end, in the line's own mileage.
    """
    line = _sample(coords, SAMPLE_M, limit_m=math.inf)
    if len(line) < 2:
        return None
    heights = sample_elevations([(lon, lat) for lon, lat, _ in line])
    if heights is None:
        return None
    top = max(range(len(line)), key=lambda index: heights[index])
    best: list[int] = [top]
    for step in (1, -1):
        walk = [top]
        index = top + step
        while 0 <= index < len(line) and heights[index] <= heights[walk[-1]]:
            if abs(line[index][2] - line[top][2]) > MAX_RUNOUT_M:
                break
            walk.append(index)
            index += step
        drop, length = heights[top] - heights[walk[-1]], len(walk)
        if (drop, length) > (heights[top] - heights[best[-1]], len(best)):
            best = walk
    if len(best) < 2:
        return None
    samples = [(line[i][0], line[i][1], abs(line[i][2] - line[top][2])) for i in best]
    # The release's mile first, then the walk's end, in the line's own mileage.
    return samples, [heights[i] for i in best], (line[best[0]][2] / M_PER_MI, line[best[-1]][2] / M_PER_MI)


def _steps(
    point: dict,
    trail: dict | None,
    trails: list[dict],
    samples: list[tuple[float, float, float]],
    drop_m: float,
    miles: tuple[float, float] | None,
    clock: Callable[[float], float],
) -> list[dict]:
    """miles is the source route's range the flow covers; None leaves out the step for it.

    clock gives the front's arrival, in seconds, at a distance down the path.
    """
    release = samples[0]
    stop = samples[-1]
    name = (trail or {}).get("name") or point.get("trail_name") or "the trail"
    lower, upper = miles or (0.0, 0.0)
    steps = [
        _step("release", "release", "Slope releases", 0, release, 0, 0, None, None, None, point.get("level")),
        _step(
            "channel",
            "channel",
            "Flow enters the channel",
            _time_at(samples, CHANNEL_M, clock),
            _sample_at(samples, CHANNEL_M),
            min(CHANNEL_M, stop[2]),
            drop_m * min(1, CHANNEL_M / max(stop[2], 1)),
            None,
            None,
            None,
            point.get("level"),
        ),
        _step(
            "trail-source",
            "trail",
            f"Reaches {name}, mi {lower:.1f}–{upper:.1f}",
            _time_at(samples, max(CHANNEL_M, stop[2] * 0.15), clock),
            _sample_at(samples, max(CHANNEL_M, stop[2] * 0.15)),
            stop[2] * 0.15,
            drop_m * 0.15,
            name,
            round(lower, 2),
            round(upper, 2),
            point.get("level") or "high",
        ),
    ]
    if miles is None:
        steps.pop()
    for extra in _crossed(trail, trails, samples, clock)[:3]:
        steps.append(extra)
    steps.append(
        _step(
            "stop",
            "stop",
            "Flow stops",
            round(clock(stop[2]), 1),
            stop,
            stop[2],
            drop_m,
            None,
            None,
            None,
            None,
        )
    )
    steps.sort(key=lambda step: (step["t_s"], step["kind"] != "release"))
    return steps


def _crossed(
    source: dict | None,
    trails: list[dict],
    samples: list[tuple[float, float, float]],
    clock: Callable[[float], float],
) -> list[dict]:
    found: list[dict] = []
    source_id = None if source is None else str(source.get("id"))
    for trail in trails:
        if str(trail.get("id")) == source_id:
            continue
        coords = _line(trail)
        if len(coords) < 2:
            continue
        hit: tuple[float, list[float]] | None = None
        for coord in coords[:: max(1, len(coords) // 24)]:
            for lon, lat, dist in samples:
                if _haversine((lon, lat), (coord[0], coord[1])) <= 90:
                    if hit is None or dist < hit[0]:
                        hit = (dist, coord)
                    break
        if hit is None:
            continue
        dist, coord = hit
        miles = _trail_miles(trail, [(coord[0], coord[1], 0.0)])
        found.append(
            _step(
                f"trail-{trail['id']}",
                "trail",
                f"Reaches {trail.get('name')}, mi {max(0, miles - 0.2):.1f}–{miles:.1f}",
                round(clock(dist), 1),
                (coord[0], coord[1], dist),
                dist,
                None,
                trail.get("name"),
                round(max(0, miles - 0.2), 2),
                round(miles, 2),
                "moderate",
            )
        )
    found.sort(key=lambda step: step["t_s"])
    return found


def _step(step_id, kind, title, t_s, where, distance_m, drop_m, trail_name, start_mile, end_mile, level) -> dict:
    return {
        "id": step_id,
        "kind": kind,
        "title": title,
        "t_s": round(float(t_s), 1),
        "lon": where[0],
        "lat": where[1],
        "distance_m": None if distance_m is None else round(float(distance_m), 1),
        "drop_m": None if drop_m is None else round(float(drop_m), 1),
        "trail_name": trail_name,
        "start_mile": start_mile,
        "end_mile": end_mile,
        "level": level,
    }


def _sample_at(samples: list[tuple[float, float, float]], dist: float) -> tuple[float, float, float]:
    for sample in samples:
        if sample[2] >= dist:
            return sample
    return samples[-1]


def _time_at(samples: list[tuple[float, float, float]], dist: float, clock: Callable[[float], float]) -> float:
    return round(clock(min(dist, samples[-1][2])), 1)


def _trail_miles(trail: dict | None, samples: list[tuple[float, float, float]]) -> float:
    if not trail:
        return 0.0
    length_km = float(trail.get("length_km") or 0)
    if length_km <= 0:
        length_km = _haversine_line(_line(trail)) / 1000
    return length_km * 0.621371


def _source_trail(point: dict, trails: list[dict]) -> dict | None:
    wanted = point.get("trail_id")
    for trail in trails:
        if str(trail.get("id")) == str(wanted):
            return trail
    name = point.get("trail_name")
    for trail in trails:
        if trail.get("name") == name:
            return trail
    return trails[0] if trails else None


def _sample(coords: list[list[float]], step_m: float, limit_m: float = MAX_RUNOUT_M) -> list[tuple[float, float, float]]:
    samples: list[tuple[float, float, float]] = [(coords[0][0], coords[0][1], 0.0)]
    dist_along = 0.0
    carry = 0.0
    for start, end in zip(coords, coords[1:], strict=False):
        seg = _haversine((start[0], start[1]), (end[0], end[1]))
        if seg < 0.5:
            continue
        pos = 0.0
        while pos < seg - 1e-6:
            remain = step_m - carry
            if pos + remain <= seg + 1e-6:
                pos = min(seg, pos + remain)
                dist_along += remain
                carry = 0.0
                frac = pos / seg
                samples.append((start[0] + (end[0] - start[0]) * frac, start[1] + (end[1] - start[1]) * frac, dist_along))
            else:
                dist_along += seg - pos
                carry += seg - pos
                pos = seg
        if dist_along > limit_m:
            break
    last = coords[-1]
    if _haversine((samples[-1][0], samples[-1][1]), (last[0], last[1])) > 8 and samples[-1][2] < limit_m:
        samples.append((last[0], last[1], samples[-1][2] + _haversine((samples[-1][0], samples[-1][1]), (last[0], last[1]))))
    return samples


def _haversine_line(coords: list[list[float]]) -> float:
    return sum(_haversine((a[0], a[1]), (b[0], b[1])) for a, b in zip(coords, coords[1:], strict=False))


def _try_dem(point: dict, trails: list[dict]) -> dict | None:
    """Reserved for Holmgren routing on data/processed/features.tif.

    The grid is not in this checkout, and a half-wired read would pretend the
    frames came from 30 m terrain. Until that path is proven, the trail corridor
    is the runout, and its method line says so.
    """
    del point, trails
    return None
