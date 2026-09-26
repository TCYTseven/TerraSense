from app.mountain_catalog import build_seed_list, slugify


def test_slugify():
    assert slugify("Mount Rainier") == "mount-rainier"
    assert slugify("K2") == "k2"


def test_build_seed_list_keeps_rainier_live():
    rows = [{"name": "Everest", "lat": 27.99, "lon": 86.92, "elevation_m": 8849, "region": "Nepal"}]
    out = build_seed_list(rows)
    rainier = next(m for m in out if m["slug"] == "mount-rainier")
    assert rainier["is_live"] is True
