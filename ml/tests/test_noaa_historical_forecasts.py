from __future__ import annotations

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.download_noaa_historical_forecasts import (
    _cycle_for,
    _descriptor_matches,
    _message_range,
)


def test_as_of_cycle_uses_completed_run() -> None:
    reference = pd.Timestamp("2024-01-01T00:00:00Z")
    assert _cycle_for(reference, 6) == pd.Timestamp("2023-12-31T18:00:00Z")
    reference = pd.Timestamp("2024-01-01T15:00:00Z")
    assert _cycle_for(reference, 6) == pd.Timestamp("2024-01-01T06:00:00Z")


def test_index_selection_requires_the_matching_accumulation_interval() -> None:
    assert _descriptor_matches("d=2024010100:APCP:surface:6-12 hour acc fcst:ens mean", "apcp", 12)
    assert not _descriptor_matches("d=2024010100:APCP:surface:0-12 hour acc fcst:ens mean", "apcp", 12)
    assert _descriptor_matches("d=2024010100:TMP:2 m above ground:12 hour fcst:ens mean", "tmp2m", 12)


def test_message_range_uses_next_index_offset() -> None:
    index = b"1:100:d=2024010100:HGT:surface:6 hour fcst\n2:250:d=2024010100:APCP:surface:0-6 hour acc fcst:ens mean\n3:500:d=2024010100:TMP:2 m above ground:6 hour fcst:ens mean\n"
    assert _message_range(index, "apcp", 6) == (250, 499)
