from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import download_caic_avalanche_data as caic  # noqa: E402


def _row(event_id: str = "a-1") -> dict:
    return {
        "id": event_id,
        "observed_at": "2024-02-03T18:00:00Z",
        "latitude": 39.1,
        "longitude": -106.5,
        "type_code": "SS",
        "problem_type": "storm",
        "primary_trigger": "N",
        "relative_size": "R2",
        "destructive_size": "D2",
        "aspect": "NW",
        "elevation_feet": 12000,
        "angle_average": 37.0,
        "water_year": 2024,
        "observation_report": {"status": "approved"},
    }


def test_query_url_is_as_of_bounded_and_deterministic() -> None:
    url = caic.query_url(start_date="2020-01-01", end_date="2020-01-31", page=2, per_page=250)
    assert "page=2" in url
    assert "per=250" in url
    assert "observed_at_gteq" in url
    assert "2020-01-01T00%3A00%3A00.000Z" in url
    assert "observed_at_lteq" in url


def test_normalize_event_preserves_missing_values_and_provenance() -> None:
    normalized = caic.normalize_event(_row())
    assert normalized is not None
    assert normalized["event_id"] == "a-1"
    assert normalized["slope_angle_average"] == 37.0
    assert normalized["source"] == "CAIC"
    assert caic.normalize_event({"id": "missing-location", "observed_at": "2024-01-01"}) is None


def test_normalize_control_requires_explicit_no_avalanche_and_coordinates() -> None:
    row = {
        "id": "r-1",
        "observed_at": "2024-02-03T18:00:00Z",
        "avalanche_observations_count": 0,
        "backcountry_zone": {"title": "Test zone"},
        "snowpack_observations": [{"latitude": 39.2, "longitude": -106.4}],
        "weather_observations": [],
    }
    control = caic.normalize_control(row)
    assert control is not None
    assert control["label"] == 0
    assert control["label_confidence"] == "coverage_backed_no_avalanche_report"
    assert caic.normalize_control({**row, "avalanche_observations_count": 1}) is None
    assert caic.normalize_control({**row, "avalanche_observations_count": None}) is None
    assert caic.normalize_control({**row, "snowpack_observations": []}) is None


def test_download_paginates_and_stops_at_short_page(tmp_path, monkeypatch) -> None:
    pages = [[_row("a-1"), _row("a-2")], [_row("a-3")]]
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(caic, "fetch_page", fake_fetch)
    result = caic.download(start_date="2020-01-01", end_date="2020-01-31", out_dir=tmp_path, per_page=2)

    assert result["pages"] == 2
    assert result["records"] == 3
    assert result["normalized_events"] == 3
    assert len(calls) == 2
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    events = json.loads((tmp_path / "events.json").read_text())
    assert manifest["training_status"] == "acquired_for_audit_only"
    assert {event["event_id"] for event in events} == {"a-1", "a-2", "a-3"}


def test_download_can_cache_coverage_controls(tmp_path, monkeypatch) -> None:
    def fake_fetch(url: str, **_kwargs):
        if "observation_reports" in url:
            return [{
                "id": "r-1", "observed_at": "2024-02-03T18:00:00Z",
                "avalanche_observations_count": 0,
                "snowpack_observations": [{"latitude": 39.2, "longitude": -106.4}],
            }]
        return [_row()]

    monkeypatch.setattr(caic, "fetch_page", fake_fetch)
    result = caic.download(start_date="2020-01-01", end_date="2020-01-31", out_dir=tmp_path, per_page=2, include_controls=True)
    assert result["controls"]["records"] == 1
    assert json.loads((tmp_path / "controls.json").read_text())[0]["label"] == 0
