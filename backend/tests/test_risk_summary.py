"""The hill card's numbers come from the saved map the heat layer is rendered from."""

import pytest

from app.ml import probability
from app.ml.hazard import line_exposure
from app.risk import HIGH_THRESHOLD, risk_level
from app.risk_summary import TOP_TRAILS, risk_summary, saved_map
from app.trailscan import scan_trails

from .conftest import storm_rain


@pytest.fixture(scope="module")
def storm_map(tmp_path_factory):
    path = tmp_path_factory.mktemp("maps") / "probability.tif"
    probability.write(probability.score(storm_rain()), path)
    return path


def test_scores_are_read_from_the_saved_map(db_conn, storm_map) -> None:
    summary = risk_summary(db_conn, "mount-rainier", storm_map)
    grid, _ = saved_map(storm_map)
    scores = scan_trails(db_conn, "mount-rainier", grid)

    assert summary["method"] == probability.MODEL_B_METHOD
    assert summary["overall"]["trails_scored"] == len(scores)
    assert summary["overall"]["score"] == pytest.approx(max(s.max_probability for s in scores), abs=1e-4)
    assert summary["overall"]["level"] == risk_level(summary["overall"]["score"])
    assert 0 < len(summary["trails"]) <= TOP_TRAILS

    by_id = {s.trail_id: s for s in scores}
    for trail in summary["trails"]:
        score = by_id[trail["trail_id"]]
        assert trail["max_probability"] == pytest.approx(score.max_probability, abs=1e-4)
        assert trail["level"] == risk_level(score.max_probability)
        assert trail["worst_point"] is not None


def test_a_storm_puts_the_top_trail_at_high_with_its_terrain(db_conn, storm_map) -> None:
    summary = risk_summary(db_conn, "mount-rainier", storm_map)
    top = summary["trails"][0]

    assert top["max_probability"] >= HIGH_THRESHOLD
    assert top["slope_deg"] is not None and 0 <= top["slope_deg"] <= 90
    assert top["factor"]
    assert summary["mean_slope_deg"] is not None


def test_the_worst_point_is_on_the_trail(db_conn, storm_map) -> None:
    grid, _ = saved_map(storm_map)
    summary = risk_summary(db_conn, "mount-rainier", storm_map)
    trail = db_conn.execute("SELECT geom FROM trails WHERE id = %s", (summary["trails"][0]["trail_id"],)).fetchone()
    geom = trail["geom"] if isinstance(trail, dict) else trail[0]
    exposure = line_exposure(grid, geom["coordinates"])

    assert list(exposure.worst_point) == summary["trails"][0]["worst_point"]


def test_no_saved_map_means_no_scores(db_conn, tmp_path) -> None:
    assert risk_summary(db_conn, "mount-rainier", tmp_path / "missing.tif") is None
