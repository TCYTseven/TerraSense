from app.mountain_catalog import build_seed_list, pick_stratified, slugify


def test_slugify():
    assert slugify("Mount Rainier") == "mount-rainier"
    assert slugify("K2") == "k2"


def test_pick_stratified_spreads_latitude():
    rows = [
        {"name": f"Antarctic {i}", "lat": -80.0, "lon": i, "elevation_m": 4000 + i, "region": "AQ"}
        for i in range(120)
    ] + [
        {"name": f"Alp {i}", "lat": 46.0, "lon": 8.0 + i * 0.1, "elevation_m": 3500 + i, "region": "CH"}
        for i in range(50)
    ]
    picked = pick_stratified(rows, target=100)
    alps = sum(1 for r in picked if r["lat"] > 30)
    assert alps >= 20


def test_build_seed_list_keeps_rainier_live():
    rows = [{"name": "Everest", "lat": 27.99, "lon": 86.92, "elevation_m": 8849, "region": "Nepal"}]
    out = build_seed_list(rows)
    rainier = next(m for m in out if m["slug"] == "mount-rainier")
    assert rainier["is_live"] is True
