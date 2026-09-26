from app.mountain_catalog import (
    LATITUDE_BANDS,
    LON_SLICES,
    MIN_ELEVATION_M,
    _band_quotas,
    _split_tile,
    _tile_query,
    build_seed_list,
    iter_tiles,
    pick_stratified,
    slugify,
    space_out,
)


def test_slugify():
    assert slugify("Mount Rainier") == "mount-rainier"
    assert slugify("K2") == "k2"


def test_iter_tiles_covers_globe():
    tiles = iter_tiles()
    assert len(tiles) == len(LATITUDE_BANDS) * len(LON_SLICES)
    for south, west, north, east in tiles:
        assert -90 <= south < north <= 90
        assert -180 <= west < east <= 180
    assert min(t[0] for t in tiles) == -90
    assert max(t[2] for t in tiles) == 90
    assert min(t[1] for t in tiles) == -180
    assert max(t[3] for t in tiles) == 180


def test_tile_query_has_bbox_and_elevation_filter():
    query = _tile_query(30, -120, 45, -90)
    assert "(30,-120,45,-90)" in query
    assert f'(if:number(t["ele"])>={MIN_ELEVATION_M})' in query
    assert "out body" in query  # "out tags" drops lat/lon and broke seed generation


def test_split_tile_halves_longer_axis():
    # A 15x30 tile is wider than tall: split along longitude.
    assert _split_tile(45, 0, 60, 30) == ((45, 0, 60, 15), (45, 15, 60, 30))
    # A square tile also splits along longitude (ties go to longitude).
    assert _split_tile(45, 0, 60, 15) == ((45, 0, 60, 7.5), (45, 7.5, 60, 15))
    # A tile taller than wide splits along latitude.
    assert _split_tile(45, 0, 60, 7.5) == ((45, 0, 52.5, 7.5), (52.5, 0, 60, 7.5))


def test_band_quotas_even_share_with_leftover_redistribution():
    # 4 occupied bands, target 200: the two 40-peak bands keep all 40,
    # the leftover flows to the fuller bands instead of vanishing.
    counts = [600, 0, 0, 40, 80, 40, 0, 0, 0, 0]
    quotas = _band_quotas(counts, target=200)
    assert quotas[3] == 40
    assert quotas[5] == 40
    assert quotas[4] == 60
    assert quotas[0] == 60
    assert sum(quotas) == 200


def test_space_out_thins_ridge_lines():
    """Fifty peaks 0.1 degrees apart must not become fifty stacked pins."""
    rows = [
        {"name": f"Ridge {i}", "lat": 46.0, "lon": 8.0 + i * 0.1, "elevation_m": 3000 + i, "region": "CH"}
        for i in range(50)
    ]
    picked = pick_stratified(rows, target=50)
    assert len(picked) <= 6
    lons = sorted(r["lon"] for r in picked)
    assert all(b - a >= 1.0 for a, b in zip(lons, lons[1:]))
    # The summit of the ridge survives the thinning.
    assert max(r["elevation_m"] for r in picked) == 3049


def test_space_out_keeps_spaced_peaks():
    rows = [
        {"name": f"Peak {i}", "lat": 40.0, "lon": -110.0 + i * 1.01, "elevation_m": 3000, "region": "US"}
        for i in range(10)
    ]
    assert len(space_out(rows)) == 10


def _grid_peaks(name, south, lon0, count, base_ele):
    # A 1.01-degree grid, 10 latitude levels: already spaced, so space_out keeps all.
    return [
        {
            "name": f"{name} {i}",
            "lat": south + (i % 10) * 1.01,
            "lon": lon0 + (i // 10) * 1.01,
            "elevation_m": base_ele + i,
            "region": name,
        }
        for i in range(count)
    ]


def test_pick_stratified_spreads_latitude():
    rows = [
        {"name": f"Antarctic {i}", "lat": -80.0, "lon": -120 + i * 1.01, "elevation_m": 4000 + i, "region": "AQ"}
        for i in range(120)
    ] + [
        {"name": f"Alp {i}", "lat": 46.0, "lon": 8.0 + i * 1.01, "elevation_m": 3500 + i, "region": "CH"}
        for i in range(50)
    ]
    picked = pick_stratified(rows, target=100)
    alps = sum(1 for r in picked if r["lat"] > 30)
    assert alps >= 20


def test_pick_stratified_regional_quotas():
    """NH and Asian ranges get slots even when the southern hemisphere has far more raw peaks."""
    rows = (
        _grid_peaks("Andes", -59.5, -75.0, 300, 5000)
        + _grid_peaks("Antarctica", -89.5, 0.0, 300, 4500)
        + _grid_peaks("Rockies", 31.0, -115.0, 40, 3500)
        + _grid_peaks("Japan", 31.0, 132.0, 40, 2500)
        + _grid_peaks("Alps", 45.5, 5.0, 40, 3800)
        + _grid_peaks("Himalaya", 16.0, 80.0, 40, 8000)
    )
    picked = pick_stratified(rows, target=200)

    by_region = {}
    for row in picked:
        by_region[row["region"]] = by_region.get(row["region"], 0) + 1

    # Himalaya (band 15..30) and Alps (band 45..60) are alone in their bands: full 40 each.
    assert by_region.get("Himalaya", 0) == 40
    assert by_region.get("Alps", 0) == 40
    # Rockies and Japan share band 30..45; the lon round-robin splits the band's quota.
    assert by_region.get("Rockies", 0) >= 20
    assert by_region.get("Japan", 0) >= 20
    # The 600 southern rows cannot take more than their two bands' even share.
    southern = by_region.get("Andes", 0) + by_region.get("Antarctica", 0)
    assert southern <= 100
    assert len(picked) == 200


def test_pick_stratified_spreads_longitude_within_band():
    rows = [
        {"name": f"Rocky {i}", "lat": 31.0 + (i % 10) * 1.01, "lon": -115.0 + (i // 10) * 1.01,
         "elevation_m": 4400 - i, "region": "US"}
        for i in range(100)
    ] + [
        {"name": f"Nihon {i}", "lat": 31.0 + (i % 10) * 1.01, "lon": 128.0 + (i // 10) * 1.01,
         "elevation_m": 2200 + i, "region": "JP"}
        for i in range(100)
    ]
    picked = pick_stratified(rows, target=100)
    japan = sum(1 for r in picked if r["lon"] > 100)
    # Every US peak outranks every Japanese peak by elevation; the slice
    # round-robin still gives Japan half the band.
    assert japan == 50


def test_build_seed_list_keeps_rainier_live():
    rows = [{"name": "Everest", "lat": 27.99, "lon": 86.92, "elevation_m": 8849, "region": "Nepal"}]
    out = build_seed_list(rows)
    rainier = next(m for m in out if m["slug"] == "mount-rainier")
    assert rainier["is_live"] is True


def test_build_seed_list_gives_rainier_breathing_room():
    rows = [
        {"name": "Little Tahoma Peak", "lat": 46.85, "lon": -121.72, "elevation_m": 3395, "region": "US"},
        {"name": "Everest", "lat": 27.99, "lon": 86.92, "elevation_m": 8849, "region": "Nepal"},
    ]
    out = build_seed_list(rows)
    names = {m["name"] for m in out}
    assert "Little Tahoma Peak" not in names  # would stack on Rainier's pin
    assert "Everest" in names
    assert "Mount Rainier" in names
