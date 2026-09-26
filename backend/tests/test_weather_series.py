"""The hourly series the agents read: gaps, alignment, and what "no data" must look like.

A conditions series feeds straight into an agent's prompt, so a gap filled with the wrong number
is a fact the model will reason from. Open-Meteo returns soil moisture as all nulls at Paradise's
elevation; a zero there reads as bone-dry ground on a mountain that just took 61 mm of rain.
"""

from datetime import UTC, datetime

import pytest

from app.weather import EXTRA_SERIES, _parse, _series, freeze_thaw_cycles, summarize


def test_a_series_with_no_readings_is_absent_not_zero():
    assert _series([None] * 10) == []


def test_a_gap_is_filled_from_the_last_reading():
    assert _series([1.0, None, None, 4.0]) == [1.0, 1.0, 1.0, 4.0]


def test_a_leading_gap_is_filled_from_the_first_reading():
    """Never 0.0: the series opens before the model has an answer, it does not read zero."""
    assert _series([None, None, 3.0, 4.0]) == [3.0, 3.0, 3.0, 4.0]


def test_filling_keeps_the_length_so_now_index_still_points_at_now():
    values = [None, 2.0, None, 4.0, None]
    assert len(_series(values)) == len(values)


def payload(hours: int, **series) -> dict:
    times = [f"2026-09-25T{h:02d}:00" for h in range(hours)]
    return {"hourly": {"time": times, "precipitation": [0.0] * hours, **series}}


def test_an_all_null_series_reaches_the_summary_as_none():
    hours = 6
    data = payload(hours, soil_moisture_0_to_7cm=[None] * hours, temperature_2m=[2.0] * hours)
    rain = _parse(data, "fixture", datetime(2026, 9, 25, 3, tzinfo=UTC))
    assert rain.soil_moisture == []
    assert summarize(rain).soil_moisture_now is None
    assert summarize(rain).temp_now_c == 2.0


def test_a_source_without_the_extra_series_still_parses():
    """A fixture saved with precipitation only must not break the run."""
    rain = _parse(payload(4), "fixture", datetime(2026, 9, 25, 1, tzinfo=UTC))
    for field in EXTRA_SERIES.values():
        assert getattr(rain, field) == []
    totals = summarize(rain)
    assert totals.past_72h_mm == 0.0 and totals.temp_now_c is None


def test_every_extra_series_lines_up_with_the_hours():
    hours = 8
    data = payload(hours, **{key: [float(i) for i in range(hours)] for key in EXTRA_SERIES})
    rain = _parse(data, "fixture", datetime(2026, 9, 25, 5, tzinfo=UTC))
    for field in EXTRA_SERIES.values():
        assert len(getattr(rain, field)) == len(rain.times)
    # now_index points at 05:00, so at_now reads that hour and not a neighbour.
    assert rain.now_index == 5 and rain.at_now(rain.temperature_c) == 5.0


@pytest.mark.parametrize(("temps", "cycles"), [
    ([1.0, 1.0, 1.0], 0),
    ([1.0, -1.0], 0),            # one crossing is not a cycle
    ([1.0, -1.0, 1.0], 1),       # down and back up
    ([1.0, -1.0, 1.0, -1.0, 1.0], 2),
    ([], 0),
])
def test_freeze_thaw_counts_round_trips_not_crossings(temps, cycles):
    assert freeze_thaw_cycles(temps) == cycles
