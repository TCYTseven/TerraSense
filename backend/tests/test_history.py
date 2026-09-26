"""Historical landslide pin contract tests (step 14)."""

from app.history import historical_events


def test_rainier_inventory_is_non_empty_and_in_bounds() -> None:
    events = historical_events("mount-rainier")

    assert len(events) == 33
    assert all(event.catalog.startswith("Washington State Landslide Inventory Database") for event in events)
    assert all(event.location_accuracy == "1km" for event in events)
    assert all(-121.93 <= event.lon <= -121.54 for event in events)
    assert all(46.76 <= event.lat <= 46.96 for event in events)
    assert all(event.source_link and event.source_link.startswith("https://") for event in events)


def test_static_mountains_have_no_catalog_events() -> None:
    assert historical_events("mount-fuji") == []
