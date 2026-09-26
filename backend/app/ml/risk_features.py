"""Leakage-aware feature generation shared by offline training and live inference.

The functions here operate on plain Python sequences so the API and the offline ML environment
can use the same calculations without importing pandas, LightGBM, or a database.  A feature at
reference time ``T`` is built from observations at or before ``T`` and forecast values explicitly
marked as available at ``T``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable

from .risk_contract import MODEL_FEATURES


def _finite(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def _sum(values: Iterable[float | None]) -> float:
    return round(sum(_finite(values)), 5)


def _mean(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(mean(clean), 5) if clean else None


def _max(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(max(clean), 5) if clean else None


def _min(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(min(clean), 5) if clean else None


def _window(
    times: list[datetime],
    values: list[float | None],
    start: datetime,
    end: datetime,
    *,
    include_end: bool = False,
) -> list[float]:
    """Return values in [start, end), or [start, end] when explicitly requested."""
    def inside(time: datetime) -> bool:
        return start <= time <= end if include_end else start <= time < end

    return _finite(
        value
        for time, value in zip(times, values, strict=False)
        if inside(time)
    )


def _past_window(times: list[datetime], values: list[float | None], reference: datetime, hours: int) -> list[float]:
    # A measurement stamped exactly at T is available to an operational forecast issued at T.
    # The explicit inclusive end also keeps this function aligned with the sample builder, which
    # passes observations through T and rejects only observations after T.
    return _window(times, values, reference - timedelta(hours=hours), reference, include_end=True)


def _future_window(times: list[datetime], values: list[float | None], reference: datetime, hours: int) -> list[float]:
    return _window(times, values, reference, reference + timedelta(hours=hours), include_end=False)


def _last_value(times: list[datetime], values: list[float | None], reference: datetime) -> float | None:
    candidates = [value for time, value in zip(times, values, strict=False) if time <= reference and value is not None]
    return candidates[-1] if candidates else None


def _consecutive_wet(times: list[datetime], values: list[float | None], reference: datetime, threshold: float = 0.1) -> int:
    """Count consecutive hourly wet observations ending at the last observed hour before T."""
    observed = [(time, value) for time, value in zip(times, values, strict=False) if time <= reference]
    count = 0
    for _, value in reversed(observed):
        if value is None or float(value) < threshold:
            break
        count += 1
    return count


def _hours_since(times: list[datetime], values: list[float | None], reference: datetime, threshold: float) -> float | None:
    observed = [(time, value) for time, value in zip(times, values, strict=False) if time <= reference]
    for time, value in reversed(observed):
        if value is not None and float(value) >= threshold:
            return round(max(0.0, (reference - time).total_seconds() / 3600), 3)
    return None


def _crossings(values: list[float]) -> int:
    if not values:
        return 0
    above = [value > 0 for value in values]
    return sum(left != right for left, right in zip(above, above[1:], strict=False))


def _rolling_max_mean(values: list[float], width: int) -> float | None:
    """Maximum mean rate over a fixed-width accumulation window."""
    if len(values) < width:
        return None
    return _max(sum(values[index : index + width]) / width for index in range(len(values) - width + 1))


def _percentile(value: float | None, reference_values: list[float]) -> float | None:
    if value is None or not reference_values:
        return None
    return round(sum(candidate <= value for candidate in reference_values) / len(reference_values), 5)


def hourly_dynamic_features(
    times: list[datetime],
    precipitation_mm: list[float | None],
    reference_time: datetime,
    *,
    extras: dict[str, list[float | None]] | None = None,
    forecast_precipitation_mm: list[float | None] | None = None,
    forecast_times: list[datetime] | None = None,
    forecast_ensemble_mm: list[list[float | None]] | None = None,
    climatology: dict[str, list[float]] | None = None,
    quality: dict[str, float | int | bool | None] | None = None,
) -> dict[str, float | None]:
    """Build past-state and next-72-hour forecast features without crossing reference time.

    ``precipitation_mm`` may contain observed values and forecast values, but only values at or
    before ``reference_time`` are used for past features.  Forecast features use the separately
    supplied forecast series when present; this makes it impossible for a caller to accidentally
    train on realized future rain while claiming it was a forecast.
    """
    extras = extras or {}
    quality = quality or {}
    forecast_times = forecast_times or times
    forecast_values = forecast_precipitation_mm or []
    past = {hours: _past_window(times, precipitation_mm, reference_time, hours) for hours in (1, 3, 6, 12, 24, 48, 72, 168, 336, 720)}
    forecast = {hours: _future_window(forecast_times, forecast_values, reference_time, hours) for hours in (6, 12, 24, 48, 72)}

    values: dict[str, float | None] = {
        "rain_30m": past[1][-1] / 2 if past[1] else None,
        "rain_1h": _sum(past[1]),
        "rain_3h": _sum(past[3]),
        "rain_6h": _sum(past[6]),
        "rain_12h": _sum(past[12]),
        "rain_24h": _sum(past[24]),
        "rain_48h": _sum(past[48]),
        "rain_72h": _sum(past[72]),
        "rain_7d": _sum(past[168]),
        "rain_14d": _sum(past[336]),
        "rain_30d": _sum(past[720]),
        "max_30m_intensity_24h": _max(past[24]),
        "max_1h_intensity_24h": _max(past[24]),
        "max_3h_intensity_72h": _rolling_max_mean(past[72], 3),
        "max_6h_intensity_72h": _rolling_max_mean(past[72], 6),
        "rain_last_6h_vs_prev_6h": round((_sum(past[6]) + 0.01) / (_sum(past[12][:6]) + 0.01), 5) if len(past[12]) >= 6 else None,
        "rain_acceleration": round((_sum(past[3]) + 0.01) / (_sum(past[6][:-3]) + 0.01), 5) if len(past[6]) >= 6 else None,
        "consecutive_wet_hours": float(_consecutive_wet(times, precipitation_mm, reference_time)),
        "hours_since_heavy_rain": _hours_since(times, precipitation_mm, reference_time, 10.0),
        "hours_since_rain_started": _hours_since(times, precipitation_mm, reference_time, 0.1),
        "rain_24h_percentile": None,
        "rain_72h_percentile": None,
        "rain_7d_percentile": None,
        "rain_24h_anomaly": None,
        "rain_72h_anomaly": None,
    }

    # Climatology is supplied from training-period-only artifacts. Without it, these fields stay
    # missing instead of pretending that a short live series is a climate distribution.
    if climatology:
        for hours, key in ((24, "rain_24h"), (72, "rain_72h"), (168, "rain_7d")):
            baseline = _finite(climatology.get(key, []))
            current = values[key]
            values[f"{key}_percentile"] = _percentile(current, baseline)
            values[f"{key}_anomaly"] = round(current - mean(baseline), 5) if current is not None and baseline else None

    surface = extras.get("surface_soil_moisture") or extras.get("soil_moisture") or []
    root = extras.get("root_zone_soil_moisture") or []
    runoff = extras.get("runoff") or []
    evap = extras.get("evapotranspiration") or []
    snowmelt = extras.get("snowmelt") or []
    snow_depth = extras.get("snow_depth") or []
    temperature = extras.get("temperature_c") or extras.get("temperature") or []
    snow_fraction = extras.get("snow_fraction") or []

    surface_now = _last_value(times, surface, reference_time)
    root_now = _last_value(times, root, reference_time)
    values.update({
        "surface_soil_moisture": surface_now,
        "root_zone_soil_moisture": root_now,
        "soil_moisture_24h": _mean(_past_window(times, surface, reference_time, 24)),
        "soil_moisture_72h": _mean(_past_window(times, surface, reference_time, 72)),
        "soil_moisture_7d": _mean(_past_window(times, surface, reference_time, 168)),
        "soil_moisture_change_24h": round(surface_now - _past_window(times, surface, reference_time, 24)[0], 5)
        if surface_now is not None and _past_window(times, surface, reference_time, 24) else None,
        "soil_moisture_change_72h": round(surface_now - _past_window(times, surface, reference_time, 72)[0], 5)
        if surface_now is not None and _past_window(times, surface, reference_time, 72) else None,
        "soil_moisture_percentile": None,
        "soil_moisture_anomaly": None,
        "era5_soil_water_24h": _mean(_past_window(times, root, reference_time, 24)),
        "era5_soil_water_72h": _mean(_past_window(times, root, reference_time, 72)),
        "era5_soil_water_7d": _mean(_past_window(times, root, reference_time, 168)),
        "runoff_24h": _sum(_past_window(times, runoff, reference_time, 24)),
        "runoff_72h": _sum(_past_window(times, runoff, reference_time, 72)),
        "runoff_7d": _sum(_past_window(times, runoff, reference_time, 168)),
        "evapotranspiration_24h": _sum(_past_window(times, evap, reference_time, 24)),
        "water_balance_72h": round(_sum(past[72]) + _sum(_past_window(times, runoff, reference_time, 72)) - _sum(_past_window(times, evap, reference_time, 72)), 5),
    })

    temp_past_24 = _past_window(times, temperature, reference_time, 24)
    snow_past_24 = _past_window(times, snowmelt, reference_time, 24)
    snow_past_72 = _past_window(times, snowmelt, reference_time, 72)
    snow_now = _last_value(times, snow_depth, reference_time)
    snow_cover_now = _last_value(times, snow_fraction, reference_time)
    values.update({
        "snow_depth": snow_now,
        "snowmelt_24h": _sum(snow_past_24),
        "snowmelt_72h": _sum(snow_past_72),
        "snow_fraction": snow_cover_now,
        "snow_fraction_change_1d": round(snow_cover_now - _past_window(times, snow_fraction, reference_time, 24)[0], 5)
        if snow_cover_now is not None and _past_window(times, snow_fraction, reference_time, 24) else None,
        "snow_fraction_change_3d": round(snow_cover_now - _past_window(times, snow_fraction, reference_time, 72)[0], 5)
        if snow_cover_now is not None and _past_window(times, snow_fraction, reference_time, 72) else None,
        "snow_fraction_change_7d": round(snow_cover_now - _past_window(times, snow_fraction, reference_time, 168)[0], 5)
        if snow_cover_now is not None and _past_window(times, snow_fraction, reference_time, 168) else None,
        "rapid_snow_loss_flag": 1.0 if values.get("snow_fraction_change_3d") is not None and values["snow_fraction_change_3d"] < -0.2 else 0.0,
        "rain_on_snow_flag": 1.0 if snow_now and snow_now > 0 and _sum(forecast[24]) > 0 and _max(temp_past_24) is not None and _max(temp_past_24) > 0 else 0.0,
        "rain_on_snow_intensity": _max(forecast[24]),
        "snowmelt_plus_rain_24h": round(_sum(snow_past_24) + _sum(past[24]), 5),
        "snowmelt_plus_rain_72h": round(_sum(snow_past_72) + _sum(past[72]), 5),
        "temp_min_24h": _min(temp_past_24),
        "temp_max_24h": _max(temp_past_24),
        "freeze_thaw_cycles_7d": float(_crossings(_finite(_past_window(times, temperature, reference_time, 168))) // 2),
        "freeze_thaw_cycles_30d": float(_crossings(_finite(_past_window(times, temperature, reference_time, 720))) // 2),
        "temperature_crossed_freezing_24h": 1.0 if any(v <= 0 for v in temp_past_24) and any(v > 0 for v in temp_past_24) else 0.0,
    })

    future_temps = _future_window(forecast_times, extras.get("forecast_temperature", []), reference_time, 72)
    future_snowmelt = _future_window(forecast_times, extras.get("forecast_snowmelt", []), reference_time, 72)
    future_rain_72 = _sum(forecast[72])
    values.update({
        "forecast_rain_0_6h": _sum(forecast[6]),
        "forecast_rain_0_12h": _sum(forecast[12]),
        "forecast_rain_0_24h": _sum(forecast[24]),
        "forecast_rain_0_48h": _sum(forecast[48]),
        "forecast_rain_0_72h": future_rain_72,
        "forecast_max_1h_rain": _max(forecast[72]),
        "forecast_max_3h_rain": _rolling_max_mean(forecast[72], 3),
        "forecast_max_6h_rain": _rolling_max_mean(forecast[72], 6),
        "forecast_peak_rain_timing_h": float(forecast[72].index(max(forecast[72])) + 1) if forecast[72] else None,
        "forecast_temperature_min": _min(future_temps),
        "forecast_temperature_max": _max(future_temps),
        "forecast_snowmelt_proxy": _sum(future_snowmelt),
        "forecast_precip_ensemble_mean": _mean(_finite(v for ensemble in (forecast_ensemble_mm or []) for v in _future_window(forecast_times, ensemble, reference_time, 72))),
        "forecast_precip_p90": None,
        "forecast_precip_p95": None,
        "forecast_precip_ensemble_spread": None,
        "forecast_exceedance_probability": None,
    })
    ensemble_totals = [_sum(_future_window(forecast_times, ensemble, reference_time, 72)) for ensemble in (forecast_ensemble_mm or [])]
    if ensemble_totals:
        ordered = sorted(ensemble_totals)
        values["forecast_precip_p90"] = ordered[min(len(ordered) - 1, int(0.90 * len(ordered)))]
        values["forecast_precip_p95"] = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        values["forecast_precip_ensemble_spread"] = round(max(ordered) - min(ordered), 5)
        values["forecast_exceedance_probability"] = round(sum(v >= 25.0 for v in ordered) / len(ordered), 5)

    # Explicit quality values are part of the model input, not hidden side-channel metadata.
    values.update({
        "imerg_age_minutes": quality.get("imerg_age_minutes"),
        "smap_age_hours": quality.get("smap_age_hours"),
        "era5_age_hours": quality.get("era5_age_hours"),
        "gfs_forecast_age_hours": quality.get("gfs_forecast_age_hours"),
        "dem_available": float(bool(quality.get("dem_available", False))),
        "soilgrids_available": float(bool(quality.get("soilgrids_available", False))),
        "worldcover_available": float(bool(quality.get("worldcover_available", False))),
        "smap_available": float(bool(quality.get("smap_available", False))),
        "smap_quality_flag": quality.get("smap_quality_flag"),
        "forecast_available": float(bool(quality.get("forecast_available", bool(forecast_values)))),
    })
    quality_feature = "feature_missing_fraction"
    missing = [name for name in MODEL_FEATURES if name != quality_feature and values.get(name) is None]
    values[quality_feature] = round(len(missing) / max(1, len(MODEL_FEATURES) - 1), 5)
    return {name: values.get(name) for name in MODEL_FEATURES}


def event_cell_id(easting_m: float, northing_m: float, cell_size_m: int) -> str:
    """Stable metric cell key. The configured cell size, not source pixel size, defines the unit."""
    return f"{math.floor(easting_m / cell_size_m)}:{math.floor(northing_m / cell_size_m)}"
