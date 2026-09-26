"""The 2D runout over a synthetic terrain grid: an area, not a line, and never uphill."""

import numpy as np
import pytest

from app.ml import flow_routing, runout
from app.ml.elevation import Grid, _pixel_xy
from app.ml.pressure import rank_pressure_points

LON, LAT = -121.80, 46.80
SIZE = 120


def _valley_grid() -> Grid:
    """A slope falling south at 30 %, with a shallow V valley down the middle column."""
    px, py = _pixel_xy(LON, LAT)
    col0, row0 = int(px // 2) - SIZE // 2, int(py // 2) - 10
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    cell = Grid(None, col0, row0, 2).cell_m(LAT)
    heights = 2000 - rows * cell * 0.30 + np.abs(cols - SIZE // 2) * cell * 0.05
    return Grid(heights.astype("float64"), col0, row0, 2)


ROUTE = {
    "id": "valley",
    "name": "Valley Trail",
    "length_km": 1.0,
    "elevation_gain_m": 300,
    # Runs north (uphill) up the valley, ending near the grid's top.
    "coordinates": [[LON, LAT - 0.01 + i * 0.001] for i in range(11)],
}


@pytest.fixture
def terrain(monkeypatch):
    grid = _valley_grid()

    def heights(points):
        out = []
        for lon, lat in points:
            r, c = grid.cell_of(lon, lat)
            out.append(float(grid.heights[min(max(r, 0), SIZE - 1), min(max(c, 0), SIZE - 1)]))
        return out

    monkeypatch.setattr(runout, "sample_elevations", heights)
    monkeypatch.setattr(runout, "height_grid", lambda lon, lat, radius: grid)
    return grid


def test_spread_only_moves_downhill(terrain):
    share, dist = flow_routing.spread(terrain, LON, LAT, 1.1, 11, 6000)
    r0, c0 = terrain.cell_of(LON, LAT)
    top = terrain.heights[r0, c0]
    reached = share > 0
    assert reached.sum() > 20
    assert (terrain.heights[reached] <= top + 1e-9).all()
    # Every reached cell outside the release patch has a higher reached neighbor that fed it.
    for r, c in zip(*np.nonzero(reached & (dist > flow_routing.RELEASE_RADIUS_M)), strict=False):
        fed = [
            terrain.heights[r + dr, c + dc] > terrain.heights[r, c]
            for dr, dc in flow_routing.NEIGHBORS
            if 0 <= r + dr < SIZE and 0 <= c + dc < SIZE and reached[r + dr, c + dc]
        ]
        assert any(fed)


def test_footprint_is_an_area_with_nested_brown_bands(terrain):
    point = rank_pressure_points([ROUTE])[0]
    traced = runout.trace_runout(point, [ROUTE])
    assert traced["source"] == "dem"
    assert traced["method"] == runout.METHOD_DEM
    # Released at the route's highest point, the north end.
    assert traced["release"]["lat"] == pytest.approx(LAT, abs=0.0006)
    last = traced["frames"][-1]["geojson"]["features"]
    assert [feature["properties"]["shade"] for feature in last] == sorted((f["properties"]["shade"] for f in last), reverse=True)
    assert last[-1]["properties"]["shade"] == 0
    assert last[0]["properties"]["rim"] is True
    edge = _bounds(last[0]["geometry"])
    # Wider than a line: the footprint spans several cells east to west.
    assert edge[2] - edge[0] > 3 * terrain.cell_m(LAT) / 76_000
    # Frames only grow, and each ends further south (downhill) than the one before.
    souths = [_bounds(frame["geojson"]["features"][0]["geometry"])[1] for frame in traced["frames"]]
    assert souths == sorted(souths, reverse=True)
    stop = next(step for step in traced["steps"] if step["kind"] == "stop")
    assert stop["lat"] < traced["release"]["lat"]
    assert traced["drop_m"] > 0


def _bounds(geometry):
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    xs = [pt[0] for poly in polys for pt in poly[0]]
    ys = [pt[1] for poly in polys for pt in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)
