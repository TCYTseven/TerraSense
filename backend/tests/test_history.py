"""Historical landslide pin contract tests (step 14)."""

from app.history import historical_events


def test_rainier_inventory_is_non_empty_and_in_bounds() -> None:
    events = historical_events("mount-rainier")

    assert len(events) == 37
    assert {event.catalog for event in events} == {
        "NASA Global Landslide Catalog",
        "Washington State Landslide Inventory Database — Landslide Compilation",
    }
    assert {event.location_accuracy for event in events} == {"1km", "5km"}
    assert all(-121.93 <= event.lon <= -121.54 for event in events)
    assert all(46.76 <= event.lat <= 46.96 for event in events)
    assert all(event.source_link and event.source_link.startswith(("http://", "https://")) for event in events)


def test_static_mountains_have_no_catalog_events() -> None:
    assert historical_events("mount-fuji") == []
