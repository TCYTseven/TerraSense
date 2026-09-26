from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from download_wgs_recent_landslides import dated_audit_rows  # noqa: E402


def test_wgs_dated_rows_are_audit_only_and_preserve_unknown_trigger() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-121.8, 46.8]},
                "properties": {"RECENT_LS_ID": 7, "DATE_MOVE": 1700000000000, "CONFIDENCE": "High"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-121.7, 46.9]},
                "properties": {"RECENT_LS_ID": 8, "DATE_MOVE": None},
            },
        ],
    }
    rows = dated_audit_rows(payload)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "wgs_recent:7"
    assert rows[0]["trigger"] is None
    assert rows[0]["rainfall_trigger_status"] == "unknown_audit_only"
