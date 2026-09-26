import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "download_sources.py"
SPEC = importlib.util.spec_from_file_location("download_sources", SCRIPT)
download_sources = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(download_sources)


def test_waslid_features_emits_only_interior_points_with_training_contract():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": 7,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-121.80, 46.80], [-121.79, 46.80], [-121.79, 46.81],
                        [-121.80, 46.81], [-121.80, 46.80],
                    ]],
                },
                "properties": {
                    "LANDSLIDE_ID": 7,
                    "LANDSLIDE_TYPE": "Debris slide",
                    "LANDSLIDE_DATE": 0,
                    "DATA_CONFIDENCE": "High",
                },
            },
            {
                "type": "Feature",
                "id": 8,
                "geometry": None,
                "properties": {"LANDSLIDE_ID": 8},
            },
        ],
    }

    features = download_sources.waslid_features(payload)

    assert len(features) == 1
    feature = features[0]
    lon, lat = feature["geometry"]["coordinates"]
    west, south, east, north = download_sources.RAINIER_BBOX
    assert west <= lon <= east and south <= lat <= north
    assert feature["properties"]["location_accuracy"] == "1km"
    assert feature["properties"]["date"] == "1970-01-01"
    assert feature["properties"]["catalog"] == download_sources.WASLID_SOURCE_NAME


def test_waslid_features_rejects_arcgis_error_payload():
    with pytest.raises(ValueError, match="WASLID query did not return GeoJSON"):
        download_sources.waslid_features({"error": {"message": "service unavailable"}})


def test_fetch_waslid_sends_shared_bbox_query(monkeypatch):
    calls = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"type": "FeatureCollection", "features": []}

    def fake_get(url, **kwargs):
        calls["url"], calls["kwargs"] = url, kwargs
        return Response()

    monkeypatch.setattr(download_sources.requests, "get", fake_get)
    payload = download_sources.fetch_waslid("https://example.test/query")

    assert payload["type"] == "FeatureCollection"
    assert calls["url"] == "https://example.test/query"
    assert calls["kwargs"]["params"]["geometry"] == "-121.93,46.76,-121.54,46.96"
    assert calls["kwargs"]["params"]["outSR"] == "4326"


def test_sparse_nasa_catalog_can_be_supplemented_without_losing_provenance():
    nasa = [{
        "type": "Feature", "id": 1,
        "geometry": {"type": "Point", "coordinates": [-121.77, 46.84]},
        "properties": {"id": 1, "catalog": "NASA Global Landslide Catalog", "location_accuracy": "1km"},
    }]
    waslid = [{
        "type": "Feature", "id": 1,
        "geometry": {"type": "Point", "coordinates": [-121.80, 46.82]},
        "properties": {"id": 1, "catalog": download_sources.WASLID_SOURCE_NAME, "location_accuracy": "1km"},
    }]

    merged = download_sources.merge_catalog_features(nasa, waslid)

    assert len(merged) == 2
    assert {feature["properties"]["catalog"] for feature in merged} == {
        "NASA Global Landslide Catalog", download_sources.WASLID_SOURCE_NAME,
    }
