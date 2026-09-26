"""Leakage-aware avalanche feature generation shared by training and live inference.

Inputs are plain sequences so the offline dataset builder and FastAPI can use the exact same
window calculations.  Observations are restricted to ``T`` or earlier; future values must be
passed through the explicitly separate forecast arguments.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable

from .avalanche_contract import MODEL_FEATURES


def _finite(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def _window(times: list[datetime], values: list[float | None], start: datetime, end: datetime, *, inclusive_end: bool = False) -> list[float]:
    def inside(value: datetime) -> bool:
        return start <= value <= end if inclusive_end else start <= value < end

    return _finite(item for time, item in zip(times, values, strict=False) if inside(time))


def _past(times: list[datetime], values: list[float | None], reference: datetime, hours: int) -> list[float]:
    return _window(times, values, reference - timedelta(hours=hours), reference, inclusive_end=True)


def _future(times: list[datetime], values: list[float | None], reference: datetime, hours: int) -> list[float]:
    return _window(times, values, reference, reference + timedelta(hours=hours))


def _sum(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(sum(clean), 6) if clean else None


def _mean(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(mean(clean), 6) if clean else None


def _max(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(max(clean), 6) if clean else None


def _min(values: Iterable[float | None]) -> float | None:
    clean = _finite(values)
    return round(min(clean), 6) if clean else None


def _last(times: list[datetime], values: list[float | None], reference: datetime) -> float | None:
    candidates = [value for time, value in zip(times, values, strict=False) if time <= reference and value is not None]
    return float(candidates[-1]) if candidates else None


def _delta(times: list[datetime], values: list[float | None], reference: datetime, hours: int) -> float | None:
    current = _last(times, values, reference)
    before = _past(times, values, reference, hours)
    return round(current - before[0], 6) if current is not None and before else None


def _rolling_max(values: list[float], width: int) -> float | None:
    if len(values) < width:
        return None
    return round(max(sum(values[index:index + width]) for index in range(len(values) - width + 1)), 6)


def _freeze_thaw(values: list[float]) -> float | None:
    if not values:
        return None
    signs = [value > 0 for value in values]
    return float(sum(left != right for left, right in zip(signs, signs[1:], strict=False)) // 2)


def _direction_stats(values: list[float]) -> tuple[float | None, float | None]:
    clean = _finite(values)
    if not clean:
        return None, None
    radians = [math.radians(value % 360.0) for value in clean]
    sine, cosine = sum(math.sin(value) for value in radians), sum(math.cos(value) for value in radians)
    mode = math.degrees(math.atan2(sine, cosine)) % 360.0
    resultant = min(1.0, math.sqrt(sine * sine + cosine * cosine) / len(radians))
    spread = math.degrees(math.acos(resultant))
    return round(mode, 3), round(spread, 3)


def _snow_water_proxy(snowfall_cm: list[float]) -> float:
    # A centimeter of snowfall is retained as a transparent proxy for roughly one mm water.
    # It is not a replacement for measured SWE; the source/quality flags remain in the table.
    return sum(snowfall_cm)


def avalanche_dynamic_features(
    times: list[datetime],
    reference_time: datetime,
    *,
    precipitation_mm: list[float | None] | None = None,
    snowfall_cm: list[float | None] | None = None,
    snow_depth_m: list[float | None] | None = None,
    snow_water_equivalent_mm: list[float | None] | None = None,
    snow_cover_fraction: list[float | None] | None = None,
    snowmelt_mm: list[float | None] | None = None,
    temperature_c: list[float | None] | None = None,
    wind_speed_kmh: list[float | None] | None = None,
    wind_gust_kmh: list[float | None] | None = None,
    wind_direction_deg: list[float | None] | None = None,
    freezing_level_m: list[float | None] | None = None,
    forecast_times: list[datetime] | None = None,
    forecast_precipitation_mm: list[float | None] | None = None,
    forecast_snowfall_cm: list[float | None] | None = None,
    forecast_temperature_c: list[float | None] | None = None,
    forecast_wind_speed_kmh: list[float | None] | None = None,
    forecast_wind_gust_kmh: list[float | None] | None = None,
    forecast_wind_direction_deg: list[float | None] | None = None,
    forecast_snowmelt_mm: list[float | None] | None = None,
    forecast_snow_cover_fraction: list[float | None] | None = None,
    forecast_freezing_level_m: list[float | None] | None = None,
    forecast_ensemble_snowfall_cm: list[list[float | None]] | None = None,
    forecast_ensemble_snowfall_summary: dict[str, float | None] | None = None,
    static: dict[str, float | None] | None = None,
    context: dict[str, float | None] | None = None,
    quality: dict[str, float | int | bool | None] | None = None,
) -> dict[str, float | None]:
    """Build the canonical avalanche feature row at reference time ``T``."""
    precipitation_mm = precipitation_mm or []
    snowfall_cm = snowfall_cm or []
    snow_depth_m = snow_depth_m or []
    snow_water_equivalent_mm = snow_water_equivalent_mm or []
    snow_cover_fraction = snow_cover_fraction or []
    snowmelt_mm = snowmelt_mm or []
    temperature_c = temperature_c or []
    wind_speed_kmh = wind_speed_kmh or []
    wind_gust_kmh = wind_gust_kmh or []
    wind_direction_deg = wind_direction_deg or []
    freezing_level_m = freezing_level_m or []
    forecast_times = forecast_times or times
    forecast_precipitation_mm = forecast_precipitation_mm or []
    forecast_snowfall_cm = forecast_snowfall_cm or []
    forecast_temperature_c = forecast_temperature_c or []
    forecast_wind_speed_kmh = forecast_wind_speed_kmh or []
    forecast_wind_gust_kmh = forecast_wind_gust_kmh or []
    forecast_wind_direction_deg = forecast_wind_direction_deg or []
    forecast_snowmelt_mm = forecast_snowmelt_mm or []
    forecast_snow_cover_fraction = forecast_snow_cover_fraction or []
    forecast_freezing_level_m = forecast_freezing_level_m or []
    forecast_ensemble_snowfall_summary = forecast_ensemble_snowfall_summary or {}
    static = static or {}
    context = context or {}
    quality = quality or {}

    p24 = _past(times, precipitation_mm, reference_time, 24)
    p72 = _past(times, precipitation_mm, reference_time, 72)
    snow6 = _past(times, snowfall_cm, reference_time, 6)
    snow12 = _past(times, snowfall_cm, reference_time, 12)
    snow24 = _past(times, snowfall_cm, reference_time, 24)
    snow72 = _past(times, snowfall_cm, reference_time, 72)
    f6 = _future(forecast_times, forecast_snowfall_cm, reference_time, 6)
    f12 = _future(forecast_times, forecast_snowfall_cm, reference_time, 12)
    f24 = _future(forecast_times, forecast_snowfall_cm, reference_time, 24)
    f48 = _future(forecast_times, forecast_snowfall_cm, reference_time, 48)
    f72 = _future(forecast_times, forecast_snowfall_cm, reference_time, 72)
    forecast_rain = [_future(forecast_times, forecast_precipitation_mm, reference_time, h) for h in (6, 12, 24, 48, 72)]
    temp24 = _past(times, temperature_c, reference_time, 24)
    wind24 = _past(times, wind_speed_kmh, reference_time, 24)
    gust24 = _past(times, wind_gust_kmh, reference_time, 24)
    dirs24 = _past(times, wind_direction_deg, reference_time, 24)
    melt24 = _past(times, snowmelt_mm, reference_time, 24)
    melt72 = _past(times, snowmelt_mm, reference_time, 72)
    rain_on_snow_24 = None
    rain_on_snow_72 = None
    if snow_depth_m and temperature_c and precipitation_mm:
        snow_now = _last(times, snow_depth_m, reference_time)
        warm24 = _max(temp24)
        warm72 = _max(p72)
        if snow_now is not None and snow_now > 0 and warm24 is not None:
            rain_on_snow_24 = round(sum(value for value, temp in zip(p24, temp24[-len(p24):], strict=False) if temp > 0), 6)
        if snow_now is not None and snow_now > 0 and warm72 is not None:
            rain_on_snow_72 = round(sum(p72), 6) if warm72 > 0 else 0.0

    snow_now = _last(times, snow_depth_m, reference_time)
    swe_now = _last(times, snow_water_equivalent_mm, reference_time)
    precip24 = _sum(p24)
    snow24_total = _sum(snow24)
    wind_mode, wind_spread = _direction_stats(dirs24)
    wind_loading = None if not wind24 or not snow24 else round(max(wind24) * sum(snow24), 6)
    aspect_sin = static.get("aspect_sin_mean")
    aspect_cos = static.get("aspect_cos_mean")
    aspect_angle = math.atan2(aspect_sin, aspect_cos) if aspect_sin is not None and aspect_cos is not None else None

    def wind_alignment(directions: list[float], angle: float | None) -> float | None:
        if not directions or angle is None:
            return None
        # Wind direction is where the wind comes from; snow is preferentially deposited on the
        # lee side, hence the 180-degree rotation before comparing it to slope aspect.
        return round(mean(math.cos(angle - math.radians(direction % 360.0) - math.pi) for direction in directions), 6)

    forecast_wind = _future(forecast_times, forecast_wind_speed_kmh, reference_time, 72)
    forecast_gust = _future(forecast_times, forecast_wind_gust_kmh, reference_time, 72)
    forecast_dirs = _future(forecast_times, forecast_wind_direction_deg, reference_time, 72)
    forecast_temp = _future(forecast_times, forecast_temperature_c, reference_time, 72)
    forecast_freezing = _future(forecast_times, forecast_freezing_level_m, reference_time, 72)
    forecast_melt = _future(forecast_times, forecast_snowmelt_mm, reference_time, 72)
    forecast_cover = _future(forecast_times, forecast_snow_cover_fraction, reference_time, 72)
    ensemble_totals = [_sum(_future(forecast_times, member, reference_time, 72)) for member in (forecast_ensemble_snowfall_cm or [])]
    ensemble_totals = [value for value in ensemble_totals if value is not None]
    # Historical GEFS downloads can expose the ensemble mean and standard deviation without
    # requiring 30 separate member files.  Accept an explicit summary from that path; callers
    # must label the method in provenance because p90/p95 are distributional estimates, not
    # observed member quantiles.
    if forecast_ensemble_snowfall_summary:
        ensemble_summary = {
            "mean": forecast_ensemble_snowfall_summary.get("mean"),
            "p90": forecast_ensemble_snowfall_summary.get("p90"),
            "p95": forecast_ensemble_snowfall_summary.get("p95"),
            "spread": forecast_ensemble_snowfall_summary.get("spread"),
            "exceedance_probability": forecast_ensemble_snowfall_summary.get("exceedance_probability"),
        }
    else:
        ensemble_summary = {
            "mean": None if not ensemble_totals else round(sum(ensemble_totals) / len(ensemble_totals), 6),
            "p90": None if not ensemble_totals else sorted(ensemble_totals)[min(len(ensemble_totals) - 1, int(0.90 * len(ensemble_totals)))],
            "p95": None if not ensemble_totals else sorted(ensemble_totals)[min(len(ensemble_totals) - 1, int(0.95 * len(ensemble_totals)))],
            "spread": None if not ensemble_totals else round(max(ensemble_totals) - min(ensemble_totals), 6),
            "exceedance_probability": None if not ensemble_totals else round(sum(value >= 20.0 for value in ensemble_totals) / len(ensemble_totals), 6),
        }

    values: dict[str, float | None] = {name: static.get(name) for name in MODEL_FEATURES}
    values.update({
        "snow_depth_m": snow_now,
        "snow_depth_change_24h": _delta(times, snow_depth_m, reference_time, 24),
        "snow_depth_change_72h": _delta(times, snow_depth_m, reference_time, 72),
        "snow_depth_change_7d": _delta(times, snow_depth_m, reference_time, 168),
        "snow_cover_fraction": _last(times, snow_cover_fraction, reference_time),
        "snow_cover_change_1d": _delta(times, snow_cover_fraction, reference_time, 24),
        "snow_cover_change_3d": _delta(times, snow_cover_fraction, reference_time, 72),
        "snow_cover_change_7d": _delta(times, snow_cover_fraction, reference_time, 168),
        "swe_mm": swe_now,
        "swe_change_24h": _delta(times, snow_water_equivalent_mm, reference_time, 24),
        "swe_change_72h": _delta(times, snow_water_equivalent_mm, reference_time, 72),
        "new_snow_6h_cm": _sum(snow6), "new_snow_12h_cm": _sum(snow12),
        "new_snow_24h_cm": snow24_total, "new_snow_72h_cm": _sum(snow72),
        "new_snow_intensity_6h_cm_h": None if not snow6 else round(sum(snow6) / max(1, len(snow6)), 6),
        "snowfall_to_precip_24h": None if not precip24 or snow24_total is None else round(snow24_total / max(0.001, precip24), 6),
        "snowpack_settlement_proxy": None if snow_now is None else round(max(0.0, -(_delta(times, snow_depth_m, reference_time, 24) or 0.0)), 6),
        "snowmelt_24h": _sum(melt24),
        "snowmelt_72h": _sum(melt72),
        "solar_melt_proxy_24h": context.get("solar_melt_proxy_24h"),
        "snow_surface_temp_c": _last(times, temperature_c, reference_time),
        "snowpack_temp_gradient_proxy_c_m": context.get("snowpack_temp_gradient_proxy_c_m"),
        "recent_avalanche_count_7d": context.get("recent_avalanche_count_7d"),
        "persistent_weak_layer_signal": context.get("persistent_weak_layer_signal"),
        "snowpack_stability_observation": context.get("snowpack_stability_observation"),
        "rain_on_snow_24h": rain_on_snow_24,
        "rain_on_snow_72h": rain_on_snow_72,
        "freeze_thaw_cycles_7d": _freeze_thaw(_past(times, temperature_c, reference_time, 168)),
        "freeze_thaw_cycles_30d": _freeze_thaw(_past(times, temperature_c, reference_time, 720)),
        "temp_min_24h": _min(temp24), "temp_max_24h": _max(temp24),
        "temperature_change_24h": _delta(times, temperature_c, reference_time, 24),
        "wind_speed_now_kmh": _last(times, wind_speed_kmh, reference_time),
        "wind_speed_max_24h_kmh": _max(wind24), "wind_gust_max_24h_kmh": _max(gust24),
        "wind_direction_mode_deg": wind_mode, "wind_direction_spread_deg": wind_spread,
        "wind_loading_proxy_24h": wind_loading,
        "wind_aspect_alignment_24h": wind_alignment(dirs24, aspect_angle),
        "published_danger_rating_numeric": context.get("published_danger_rating_numeric"),
        "forecast_snowfall_0_6h": _sum(f6), "forecast_snowfall_0_12h": _sum(f12),
        "forecast_snowfall_0_24h": _sum(f24), "forecast_snowfall_0_48h": _sum(f48),
        "forecast_snowfall_0_72h": _sum(f72),
        "forecast_max_snowfall_1h": _max(f72),
        "forecast_max_snowfall_3h": _rolling_max(f72, 3),
        "forecast_max_snowfall_6h": _rolling_max(f72, 6),
        "forecast_rain_0_6h": _sum(forecast_rain[0]), "forecast_rain_0_12h": _sum(forecast_rain[1]),
        "forecast_rain_0_24h": _sum(forecast_rain[2]), "forecast_rain_0_48h": _sum(forecast_rain[3]),
        "forecast_rain_0_72h": _sum(forecast_rain[4]),
        "forecast_temp_min": _min(forecast_temp), "forecast_temp_max": _max(forecast_temp),
        "forecast_wind_max_kmh": _max(forecast_wind), "forecast_gust_max_kmh": _max(forecast_gust),
        "forecast_wind_loading_proxy": None if not forecast_wind or not f72 else round(max(forecast_wind) * sum(f72), 6),
        "forecast_wind_aspect_alignment": wind_alignment(forecast_dirs, aspect_angle),
        "forecast_solar_melt_proxy": None if not forecast_melt or not forecast_cover else round(sum(melt for melt, cover in zip(forecast_melt, forecast_cover, strict=False) if cover > 0), 6),
        "forecast_rain_on_snow_72h": None if snow_now is None or snow_now <= 0 else _sum(forecast_rain[4]),
        "forecast_freezing_level_min_m": _min(forecast_freezing), "forecast_freezing_level_max_m": _max(forecast_freezing),
        "forecast_snowfall_ensemble_mean": ensemble_summary["mean"],
        "forecast_snowfall_ensemble_p90": ensemble_summary["p90"],
        "forecast_snowfall_ensemble_p95": ensemble_summary["p95"],
        "forecast_snowfall_ensemble_spread": ensemble_summary["spread"],
        "forecast_exceedance_probability": ensemble_summary["exceedance_probability"],
    })

    missing = sum(values.get(name) is None for name in MODEL_FEATURES)
    values.update({
        "dem_available": float(bool(quality.get("dem_available", False))),
        "static_snow_terrain_available": float(bool(quality.get("static_snow_terrain_available", False))),
        "snowpack_available": float(bool(quality.get("snowpack_available", bool(snow_now is not None or swe_now is not None)))),
        "snowpack_age_hours": None if quality.get("snowpack_age_hours") is None else float(quality["snowpack_age_hours"]),
        "forecast_available": float(bool(quality.get("forecast_available", bool(f72 or forecast_rain[4])))),
        "forecast_age_hours": None if quality.get("forecast_age_hours") is None else float(quality["forecast_age_hours"]),
        "weather_station_available": float(bool(quality.get("weather_station_available", False))),
        "feature_missing_fraction": round(missing / len(MODEL_FEATURES), 6),
        "event_observation_coverage": context.get("event_observation_coverage"),
        "terrain_resolution_m": quality.get("terrain_resolution_m"),
        "weather_resolution_km": quality.get("weather_resolution_km"),
    })
    return {name: values.get(name) for name in MODEL_FEATURES}
