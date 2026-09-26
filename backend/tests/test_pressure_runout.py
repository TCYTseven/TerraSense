"""Runout ranking and the illustrative corridor, with no database and no raster."""

from app.ml.pressure import rank_pressure_points
from app.ml.runout import METHOD_TRAIL, trace_runout
from app.simulations import template_callouts

STEEP = {
    "id": "kautz",
    "name": "Kautz Creek Trail",
    "length_km": 4.8,
    "elevation_gain_m": 900,
    "coordinates": [[-121.85, 46.76], [-121.851, 46.77], [-121.852, 46.78], [-121.853, 46.79]],
}
GENTLE = {
    "id": "skyline",
    "name": "Skyline Trail",
    "length_km": 5.0,
    "elevation_gain_m": 200,
    "coordinates": [[-121.73, 46.79], [-121.732, 46.795], [-121.734, 46.80]],
}


def test_rank_puts_the_steeper_trail_first():
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
    assert len({feature["properties"]["level"] for feature in last}) >= 2


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
