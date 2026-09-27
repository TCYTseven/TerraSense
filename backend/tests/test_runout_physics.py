"""The runout's physics against the formulas and examples in context/docs/LANDSLIDE_SIMULATION.md."""

import math

import numpy as np
import pytest

from app.ml import flow_routing, runout
from app.ml import runout_physics as physics
from app.ml.elevation import Grid, _pixel_xy
from app.ml.pressure import rank_pressure_points

LON, LAT = -121.80, 46.80
SIZE = 120


def test_alpha_beta_matches_the_worked_example():
    # Section 3.2: beta = 30 degrees gives alpha about 27.4, or 25.1 one SD long.
    run = 200.0
    drop = run * math.tan(math.radians(30))
    steep = [(s, 1000 - s * drop / run) for s in np.arange(0, run + 1, 10.0)]
    flat = [(run + s, 1000 - drop - s * 0.05) for s in np.arange(10, 200, 10.0)]
    alpha, beta, found = physics.alpha_beta(steep + flat)
    assert found
    assert beta == pytest.approx(30, abs=0.01)
    assert alpha == pytest.approx(0.96 * 30 - 1.4 - 2.3, abs=0.01)


def test_beta_point_needs_thirty_metres_under_ten_degrees():
    # A 20 m ledge at 5 degrees mid-slope is not the beta point; the valley floor is.
    profile = [(0.0, 1000.0), (100.0, 942.0), (120.0, 940.2), (220.0, 882.2), (260.0, 881.0), (300.0, 880.0)]
    assert physics.beta_point(profile) == 3


def test_alpha_never_drops_below_the_floor():
    gentle = [(s, 1000 - s * math.tan(math.radians(8))) for s in range(0, 400, 20)]
    alpha, _, _ = physics.alpha_beta(gentle)
    assert alpha == physics.ALPHA_FLOOR_DEG


def test_energy_head_is_capped_at_v_max():
    cap = physics.DEBRIS_FLOW.z_delta_max_m
    assert cap == pytest.approx(15**2 / (2 * 9.81))
    assert physics.energy_head(cap, 50, 26, math.tan(math.radians(11)), cap) == cap
    # Gain the drop, lose tan(alpha) per metre.
    assert physics.energy_head(2.0, 5.0, 26.0, 0.2, cap) == pytest.approx(2.0 + 5.0 - 5.2)
    assert physics.head_speed(cap) == pytest.approx(15.0)


def test_pcm_reaches_voellmy_terminal_speed_on_a_long_slope():
    snow = physics.SNOW_AVALANCHE
    psi = math.radians(35)
    step = 26.0
    v_sq = 0.0
    for _ in range(200):
        v_sq = physics.pcm_speed_sq(v_sq, step * math.tan(psi), step, snow.mu, snow.xi_ms2, snow.flow_height_m)
    terminal = math.sqrt(snow.xi_ms2 * snow.flow_height_m * (math.sin(psi) - snow.mu * math.cos(psi)))
    assert math.sqrt(v_sq) == pytest.approx(terminal, rel=1e-6)


def test_pcm_matches_small_step_voellmy_integration():
    # The closed form over one segment equals the sled equation integrated in tiny steps.
    snow = physics.SNOW_AVALANCHE
    drop, step, v0 = 12.0, 30.0, 9.0
    exact = physics.pcm_speed_sq(v0**2, drop, step, snow.mu, snow.xi_ms2, snow.flow_height_m)
    psi = math.atan2(drop, step)
    length = math.hypot(drop, step)
    v_sq, n = v0**2, 20000
    ds = length / n
    for _ in range(n):
        v_sq += 2 * ds * (9.81 * (math.sin(psi) - snow.mu * math.cos(psi)) - 9.81 * v_sq / (snow.xi_ms2 * snow.flow_height_m))
    assert exact == pytest.approx(v_sq, rel=1e-3)


def test_pcm_stops_on_ground_flatter_than_friction():
    snow = physics.SNOW_AVALANCHE
    assert physics.pcm_speed_sq(4.0, 0.5, 100.0, snow.mu, snow.xi_ms2, snow.flow_height_m) < 0


def test_persistence_tables():
    assert physics.persistence_weight(None, physics.PERSISTENCE_COSINE) == 1
    assert physics.persistence_weight(1.0, physics.PERSISTENCE_COSINE) == pytest.approx(1)
    assert physics.persistence_weight(math.cos(math.radians(45)), physics.PERSISTENCE_COSINE) == pytest.approx(0.707)
    assert physics.persistence_weight(0.0, physics.PERSISTENCE_COSINE) == pytest.approx(0)
    assert physics.persistence_weight(0.0, physics.PERSISTENCE_PROPORTIONAL) == pytest.approx(0.4)
    assert physics.persistence_weight(-1.0, physics.PERSISTENCE_PROPORTIONAL) == pytest.approx(0)


def test_flow_py_terrain_term_is_gentler_than_raw_holmgren():
    snow = physics.SNOW_AVALANCHE
    # Phi = (psi + 90) / 2, so a nearly flat move still gets tan(45) ** 8, about 1.
    assert physics.terrain_weight(1e-6, 26, snow) == pytest.approx(1, rel=1e-4)
    steep, gentle = physics.terrain_weight(26 * math.tan(math.radians(30)), 26, snow), physics.terrain_weight(
        26 * math.tan(math.radians(20)), 26, snow
    )
    assert steep > gentle


def test_process_follows_the_place_kind():
    assert physics.process_for("mountain") is physics.SNOW_AVALANCHE
    assert physics.process_for("hill") is physics.DEBRIS_FLOW
    assert physics.process_for(None) is physics.DEBRIS_FLOW


def _bowl_grid() -> Grid:
    """A 35 percent slope falling south that flattens into a valley floor halfway down."""
    px, py = _pixel_xy(LON, LAT)
    col0, row0 = int(px // 2) - SIZE // 2, int(py // 2) - 10
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    cell = Grid(None, col0, row0, 2).cell_m(LAT)
    along = np.minimum(rows, 40) * cell * 0.35 + np.maximum(rows - 40, 0) * cell * 0.03
    heights = 2400 - along + np.abs(cols - SIZE // 2) * cell * 0.04
    return Grid(heights.astype("float64"), col0, row0, 2)


@pytest.mark.parametrize("process", [physics.DEBRIS_FLOW, physics.SNOW_AVALANCHE])
def test_front_speeds_up_down_the_slope_and_slows_to_a_stop(process):
    grid = _bowl_grid()
    # The face is about 19 degrees, so the snow reach angle must sit under it for the flow to start.
    routed = flow_routing.spread(grid, LON, LAT, process, 11 if process.reach_angle_deg else 15, 6000)
    reached = routed.share >= flow_routing.MIN_SHARE
    assert reached.sum() > 20
    # Never uphill, and later downhill: arrival grows with distance along the flow.
    r0, c0 = grid.cell_of(LON, LAT)
    assert (grid.heights[reached] <= grid.heights[r0, c0] + 1e-9).all()
    order = np.argsort(routed.dist[reached])
    arrivals = routed.arrival[reached][order]
    assert arrivals[-1] > arrivals[len(arrivals) // 2] > 0
    speeds = routed.speed[reached]
    if process.v_max_ms is not None:
        assert speeds.max() <= process.v_max_ms + 1e-9
    # The toe, on the flat floor, is slower than the peak on the steep face.
    toe = routed.speed[reached][order][-5:]
    assert toe.max() < speeds.max()


def test_mountain_runout_is_a_labeled_snow_avalanche(monkeypatch):
    grid = _bowl_grid()

    def heights(points):
        out = []
        for lon, lat in points:
            r, c = grid.cell_of(lon, lat)
            out.append(float(grid.heights[min(max(r, 0), SIZE - 1), min(max(c, 0), SIZE - 1)]))
        return out

    monkeypatch.setattr(runout, "sample_elevations", heights)
    monkeypatch.setattr(runout, "height_grid", lambda lon, lat, radius: grid)
    route = {
        "id": "bowl",
        "name": "Bowl Trail",
        "length_km": 1.0,
        "elevation_gain_m": 300,
        "coordinates": [[LON, LAT - 0.01 + i * 0.001] for i in range(11)],
    }
    point = rank_pressure_points([route])[0]
    traced = runout.trace_runout(point, [route], physics.SNOW_AVALANCHE)
    assert traced["source"] == "dem"
    assert traced["method"].startswith("Illustrative snow-avalanche runout")
    assert traced["method"].endswith("Not a forecast of timing.")
    phys = traced["physics"]
    assert phys["process"] == "snow_avalanche"
    assert phys["beta_point_found"] is True
    assert phys["reach_angle_deg"] == pytest.approx(0.96 * phys["beta_deg"] - 3.7, abs=0.1)
    assert 0 < phys["peak_speed_ms"] < 60
    times = [frame["t_s"] for frame in traced["frames"]]
    assert times == sorted(times)
    assert 8 <= len(times) <= 40
    assert traced["duration_s"] == times[-1]
    step_times = [step["t_s"] for step in traced["steps"]]
    assert step_times == sorted(step_times)
    assert max(step_times) == traced["duration_s"]
