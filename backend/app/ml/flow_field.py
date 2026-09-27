"""The runout as one continuous field the map can animate smoothly.

The polygon frames step: a 26 m cell grid drawn as nested bands, swapped every
half second. This field carries, per cell of a Web Mercator grid, how much of the
cell the flow covers, when the front arrives, and how deep the deposit is. The
map interpolates all three between cells and sweeps the front continuously, so
the edge is soft and the flow never jumps.

Wire format (JSON-ready): corners are [lon, lat] for top-left, top-right,
bottom-right, bottom-left. `cover` and `depth` are base64 uint8 rows, top row
first. `arrival` is base64 little-endian uint16: seconds / duration_s * 65534,
and 65535 where the flow never arrives.
"""

from __future__ import annotations

import base64
import math

from app.ml import flow_routing
from app.ml.elevation import ZOOM, TILE_PX, _lonlat, _pixel_xy

NEVER = 65535
PAD_CELLS = 4
BLUR_PASSES = 2
# Shade depth levels from the edge in. More levels give a smoother core-to-edge ramp.
DEPTH_LEVELS = 8


def blur(values, passes: int = 1):
    """A 3x3 mean filter applied `passes` times, close to a small Gaussian. Edges repeat 0."""
    import numpy as np

    out = values.astype("float64")
    for _ in range(passes):
        acc = out.copy()
        for dr, dc in flow_routing.NEIGHBORS:
            acc += flow_routing._shift(out, dr, dc, fill=0.0)
        out = acc / 9
    return out


def terrain_field(grid, mask, arrive_s, share, duration_s: float) -> dict | None:
    """The routed footprint as a field, cropped to the flow plus a small margin.

    arrive_s is each cell's arrival time in seconds, from the process's speed model.
    """
    import numpy as np

    if not mask.any():
        return None
    rows, cols = np.nonzero(mask)
    r0 = max(0, int(rows.min()) - PAD_CELLS)
    c0 = max(0, int(cols.min()) - PAD_CELLS)
    r1 = min(mask.shape[0], int(rows.max()) + 1 + PAD_CELLS)
    c1 = min(mask.shape[1], int(cols.max()) + 1 + PAD_CELLS)
    inside = mask[r0:r1, c0:c1]
    solid = inside.astype("float64")

    cover = blur(solid, BLUR_PASSES)
    # Arrival averaged over flow cells only (normalized convolution), so the soft rim
    # takes its neighbours' time and the 8-direction fronts round off.
    arrive = np.where(inside, arrive_s[r0:r1, c0:c1], 0.0)
    arrive = blur(arrive * solid, BLUR_PASSES) / np.maximum(cover, 1e-9)

    # Deep where the cell sits far in from the edge and where most flow passes.
    inward = flow_routing.shade_depth(inside, DEPTH_LEVELS) / (DEPTH_LEVELS - 1)
    floor = flow_routing.MIN_SHARE
    channel = np.clip(np.log(np.maximum(share[r0:r1, c0:c1], floor) / floor) / math.log(1 / floor), 0, 1)
    depth = blur(np.where(inside, 0.65 * inward + 0.35 * channel, 0.0), BLUR_PASSES)
    # A narrow flow never gets far from its edge, so scale to its own deepest cell:
    # every flow shows the full dark-core-to-pale-edge ramp.
    depth = depth / max(float(depth.max()), 1e-9)

    corners = [grid.lonlat(r0, c0), grid.lonlat(r0, c1), grid.lonlat(r1, c1), grid.lonlat(r1, c0)]
    return encode(corners, cover, np.where(cover > 0, arrive, np.nan), depth, duration_s)


def trail_field(samples: list[tuple[float, float, float]], half_width_m, clock, duration_s: float) -> dict | None:
    """A ribbon along the sampled path, widening downhill, on a z13 Mercator grid.

    samples are (lon, lat, metres along). half_width_m(dist) gives the ribbon's half
    width at that distance. clock(dist) is the front's arrival in seconds at a distance
    along the path; each pixel takes the arrival at its nearest point on the path.
    """
    import numpy as np

    if len(samples) < 2:
        return None
    lat0 = samples[0][1]
    pixel_m = 2 * math.pi * 6378137.0 * math.cos(math.radians(lat0)) / (2**ZOOM * TILE_PX)
    pts = np.array([_pixel_xy(lon, lat) for lon, lat, _ in samples])
    along = np.array([dist for *_, dist in samples])
    halves = np.array([half_width_m(dist) for dist in along]) / pixel_m
    reach = float(halves.max()) * 2 + PAD_CELLS
    x0, y0 = math.floor(pts[:, 0].min() - reach), math.floor(pts[:, 1].min() - reach)
    x1, y1 = math.ceil(pts[:, 0].max() + reach), math.ceil(pts[:, 1].max() + reach)
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)

    best = np.full(xs.shape, np.inf)  # distance over local half width
    best_along = np.zeros(xs.shape)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = b - a
        length2 = float(seg @ seg)
        t = np.zeros(xs.shape) if length2 == 0 else np.clip(((xs - a[0]) * seg[0] + (ys - a[1]) * seg[1]) / length2, 0, 1)
        dist = np.hypot(xs - (a[0] + t * seg[0]), ys - (a[1] + t * seg[1]))
        half = halves[i] + t * (halves[i + 1] - halves[i])
        ratio = dist / half
        closer = ratio < best
        best = np.where(closer, ratio, best)
        best_along = np.where(closer, along[i] + t * (along[i + 1] - along[i]), best_along)

    # 1 at the centerline, 0.5 at the ribbon edge, 0 at twice the half width.
    cover = np.clip(1 - best / 2, 0, 1)
    depth = np.clip(1 - best, 0, 1) ** 0.8
    arrive = np.where(cover > 0, np.vectorize(clock, otypes=[float])(best_along), np.nan)
    corners = [_lonlat(x0, y0), _lonlat(x1, y0), _lonlat(x1, y1), _lonlat(x0, y1)]
    return encode(corners, cover, arrive, depth, duration_s)


def encode(corners, cover, arrive_s, depth, duration_s: float) -> dict:
    import numpy as np

    span = max(duration_s, 1e-6)
    arrival = np.where(np.isfinite(arrive_s), np.clip(np.nan_to_num(arrive_s) / span, 0, 1) * (NEVER - 1), NEVER)
    return {
        "corners": [[round(lon, 7), round(lat, 7)] for lon, lat in corners],
        "width": int(cover.shape[1]),
        "height": int(cover.shape[0]),
        "cover": _b64(np.round(np.clip(cover, 0, 1) * 255).astype("<u1")),
        "arrival": _b64(np.round(arrival).astype("<u2")),
        "depth": _b64(np.round(np.clip(depth, 0, 1) * 255).astype("<u1")),
    }


def _b64(array) -> str:
    return base64.b64encode(array.tobytes()).decode("ascii")
