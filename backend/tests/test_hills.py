"""Turtle Mountain is a hill, not a catalog peak, and the API serves it as one."""

import json

from app.config import REPO_ROOT
from app.hills import TURTLE_BBOX, TURTLE_SLUG, hills, in_hill_bbox, is_hill
from app.ml.geo_susceptibility import PLACEHOLDER_INPUT, predict_summit

HILLS_PATH = REPO_ROOT / "data" / "seed" / "hills.json"


def test_hills_seed_matches_shared_facts():
    rows = json.loads(HILLS_PATH.read_text(encoding="utf-8"))
    by_slug = {row["slug"]: row for row in rows}
    assert len(by_slug) == len(rows) == 22
    hill = by_slug[TURTLE_SLUG]
    assert hill["slug"] == TURTLE_SLUG
    assert hill["name"] == "Turtle Mountain"
    assert hill["kind"] == "hill"
    assert hill["is_live"] is True
    assert hill["lat"] == 49.57694
    assert hill["lon"] == -114.41222
    assert hill["elevation_m"] == 2210
    assert hill["region"] == "Crowsnest Pass, Alberta, Canada"
    assert is_hill(TURTLE_SLUG)
    assert in_hill_bbox(TURTLE_SLUG, hill["lat"], hill["lon"])
    west, south, east, north = TURTLE_BBOX
    assert west <= hill["lon"] <= east
    assert south <= hill["lat"] <= north
    # The Frank Slide point from the shared-facts note sits in the same box.
    assert in_hill_bbox(TURTLE_SLUG, 49.59111, -114.39528)
    assert any(row["slug"] == TURTLE_SLUG for row in hills())
    for row in rows:
        assert row["kind"] == "hill"
        assert row["current_risk_level"] in {"low", "moderate", "high", "extreme"}
        if row["slug"] == TURTLE_SLUG:
            assert row["is_live"] is True
        else:
            assert row["is_live"] is False


def test_turtle_mountain_is_not_a_placeholder_sample():
    result = predict_summit(TURTLE_SLUG, 49.57694, -114.41222)
    assert result.get("input_source") != PLACEHOLDER_INPUT
    if result.get("available"):
        assert result["input_source"] == "turtle-mountain feature window"
        assert result["model_card"]["auc"] is None


def test_hill_is_not_in_the_mountain_catalog():
    hill_slugs = {row["slug"] for row in json.loads(HILLS_PATH.read_text(encoding="utf-8"))}
    for name in ("mountains.json", "mountains_test.json"):
        path = REPO_ROOT / "data" / "seed" / name
        if not path.is_file():
            continue
        slugs = {row["slug"] for row in json.loads(path.read_text(encoding="utf-8"))}
        assert hill_slugs.isdisjoint(slugs)
