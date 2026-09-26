"""Runout ranking and the illustrative corridor, with no database and no raster."""

import pytest

from app.ml import pressure, runout
from app.ml.pressure import rank_pressure_points
from app.ml.runout import METHOD_TRAIL, METHOD_TRAIL_TERRAIN, trace_runout
from app.simulation_communities import fallback_community_callout
from app.simulations import template_callouts

STEEP = {
    "id": "kautz",
    "name": "Kautz Creek Trail",
    "length_km": 4.8,
    "elevation_gain_m": 900,
    "coordinates": [[-121.85, 46.76], [-121.851, 46.77], [-121.852, 46.78], [-121.853, 46.79]],
}
# A route that climbs to a crest mid-line, dips, then climbs a lower knob.
CREST = {
    "id": "crest",
    "name": "Crest Trail",
    "length_km": 2.0,
    "elevation_gain_m": 300,
    "coordinates": [[-121.80, 46.80 + i * 0.001] for i in range(20)],
}
GENTLE = {
    "id": "skyline",
    "name": "Skyline Trail",
    "length_km": 5.0,
    "elevation_gain_m": 200,
    "coordinates": [[-121.73, 46.79], [-121.732, 46.795], [-121.734, 46.80]],
}


@pytest.fixture(autouse=True)
def no_terrain(monkeypatch):
    """No tile reads in tests. A test that wants terrain patches its own heights."""
    monkeypatch.setattr(runout, "sample_elevations", lambda points: None)
    monkeypatch.setattr(runout, "height_grid", lambda lon, lat, radius: None)


def test_rank_puts_the_steeper_trail_first(monkeypatch):
    # Keep this fallback test independent of any ignored/generated raster in the developer
    # checkout. Raster-specific behavior is covered by the tests below.
    monkeypatch.setattr(pressure, "_raster_path", lambda: None)
    points = rank_pressure_points([GENTLE, STEEP])
    assert 1 <= len(points) <= 5
    assert points[0]["rank"] == 1
    assert points[0]["trail_name"] == "Kautz Creek Trail"
    assert points[0]["id"] == "trail-kautz"
    assert points[0]["level"] in {"moderate", "high", "extreme"}


def test_runout_frames_grow_and_name_the_trail():
    point = rank_pressure_points([STEEP])[0]
    runout = trace_runout(point, [STEEP, GENTLE])
    frames = runout["frames"]
    assert 2 <= len(frames) <= 40
    times = [frame["t_s"] for frame in frames]
    assert times == sorted(times)
    assert runout["duration_s"] == frames[-1]["t_s"]
    rings = [len(frame["geojson"]["features"][0]["geometry"]["coordinates"][0]) for frame in frames]
    assert rings == sorted(rings)
    assert rings[-1] >= rings[0]
    kinds = {step["kind"] for step in runout["steps"]}
    assert {"release", "stop", "trail"} <= kinds
    assert "Illustrative" in runout["method"]
    assert runout["method"].endswith("Not a forecast of timing.")
    assert runout["method"] == METHOD_TRAIL
    assert runout["source"] == "trail"
    last = frames[-1]["geojson"]["features"]
    assert last[0]["properties"]["rim"] is True
    # Brown bands, pale edge first and dark core last, each narrower than the one under it.
    assert [feature["properties"]["shade"] for feature in last] == [4, 3, 2, 1, 0]
    assert [feature["properties"]["rim"] for feature in last] == [True, False, False, False, False]
    widths = [_span(feature) for feature in last]
    assert widths == sorted(widths, reverse=True)


def _span(feature):
    ring = feature["geometry"]["coordinates"][0]
    lons = [coord[0] for coord in ring]
    return max(lons) - min(lons)


def test_template_callouts_cover_both_audiences():
    point = rank_pressure_points([STEEP])[0]
    runout = trace_runout(point, [STEEP])
    notes = template_callouts(runout["steps"], point)
    audiences = {note["audience"] for note in notes}
    assert "rangers" in audiences
    assert "public" in audiences
    for note in notes:
        assert len(note["text"].split()) <= 40
        assert "Kautz Creek Trail" in note["text"] or note["id"] == "rangers-stop"


def test_fallback_community_callout_names_places():
    point = rank_pressure_points([STEEP])[0]
    runout = trace_runout(point, [STEEP])
    note = fallback_community_callout(
        {"slug": "mount-rainier", "name": "Mount Rainier"},
        point,
        runout["steps"],
        distance_m=runout["distance_m"],
    )
    assert note["audience"] == "communities"
    assert note["places"]
    assert len(note["text"].split()) <= 80


def test_worst_route_is_the_steepest_without_a_raster(monkeypatch):
    monkeypatch.setattr(pressure, "_raster_path", lambda: None)
    point = pressure.worst_route([GENTLE, STEEP])
    assert point["trail_name"] == "Kautz Creek Trail"
    assert pressure.worst_route([]) is None


def test_worst_route_follows_the_highest_probability_on_the_line(monkeypatch, tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    # A grid over both trails, hot only under the gentle one: probability beats grade.
    path = tmp_path / "probability.tif"
    transform = from_origin(-121.86, 46.81, 0.001, 0.001)
    grid = np.full((60, 140), 0.1, dtype="float32")
    col = int(round((-121.732 - -121.86) / 0.001))
    grid[:, col - 3 : col + 4] = 0.8
    with rasterio.open(path, "w", driver="GTiff", height=60, width=140, count=1, dtype="float32", crs="EPSG:4326", transform=transform) as dst:
        dst.write(grid, 1)
    monkeypatch.setattr(pressure, "_raster_path", lambda: path)
    point = pressure.worst_route([STEEP, GENTLE])
    assert point["trail_name"] == "Skyline Trail"
    assert point["peak"] == 0.8
    assert point["level"] == "extreme"


def test_runout_releases_at_the_top_and_never_flows_up(monkeypatch):
    def heights(points):
        # 1300 m at the south end, up to 1500 m at lat 46.805, down to 1200 m at 46.815, then up again to 1300 m.
        out = []
        for _lon, lat in points:
            north = (lat - 46.80) * 111_000
            if north <= 555:
                out.append(1300 + 200 * north / 555)
            elif north <= 1665:
                out.append(1500 - 300 * (north - 555) / 1110)
            else:
                out.append(1200 + 100 * (north - 1665) / 444)
        return out

    monkeypatch.setattr(runout, "sample_elevations", heights)
    point = rank_pressure_points([CREST])[0]
    traced = trace_runout(point, [CREST])
    assert traced["method"] == METHOD_TRAIL_TERRAIN
    assert traced["release"]["elevation_m"] == pytest.approx(1500, abs=15)
    assert abs(traced["release"]["lat"] - 46.805) < 0.001
    # It takes the longer drop (north), stops in the dip, and never climbs the knob.
    assert traced["drop_m"] == pytest.approx(300, abs=15)
    release = next(step for step in traced["steps"] if step["kind"] == "release")
    stop = next(step for step in traced["steps"] if step["kind"] == "stop")
    assert stop["lat"] > release["lat"]
    assert stop["lat"] < 46.8155
    walked = heights([(step["lon"], step["lat"]) for step in sorted(traced["steps"], key=lambda step: step["t_s"]) if step["kind"] != "trail"])
    assert walked == sorted(walked, reverse=True)
