"""Shared feature and output contract for the avalanche-risk model.

The avalanche model is deliberately separate from the landslide contract.  The prediction unit
is still a 1 km cell, but the target is an avalanche occurrence in the next 24 hours and the
feature families are snowpack- and wind-loading-specific.
"""

from __future__ import annotations

from typing import Final, Literal

PredictionState = Literal["HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"]

# Avalanche instability changes faster than the landslide product.  Keep the horizon short and
# configurable at the model boundary rather than inheriting the landslide model's 72 hours.
PREDICTION_HORIZON_HOURS: Final = 24
DEFAULT_CELL_SIZE_M: Final = 1000
DEFAULT_TARGET_PRECISION: Final = 0.85
DEFAULT_MIN_DATA_QUALITY: Final = 0.80
DEFAULT_OOD_THRESHOLD: Final = 0.35
DEFAULT_ABSTENTION_BAND: Final = 0.05
# API headline floor only; calibrated_probability and state decisions remain exact.
DEFAULT_MIN_REPORTED_PROBABILITY: Final = 0.10
DEFAULT_MIN_NEGATIVE_COVERAGE: Final = 0.80

STATIC_FEATURES: Final = (
    "elevation_mean",
    "elevation_std",
    "slope_mean",
    "slope_max",
    "slope_p90",
    "slope_28_45_fraction",
    "slope_30_45_fraction",
    "slope_gt_45_fraction",
    "aspect_sin_mean",
    "aspect_cos_mean",
    "northness_mean",
    "eastness_mean",
    "profile_curvature_mean",
    "plan_curvature_mean",
    "roughness_mean",
    "terrain_ruggedness_mean",
    "local_relief_100m",
    "local_relief_500m",
    "local_relief_1km",
    "terrain_trap_fraction",
    "starting_zone_fraction",
    "runout_terrain_fraction",
    "flow_accumulation_mean",
    "dist_drainage_mean",
    "forest_fraction",
    "snow_ice_fraction",
)

SNOWPACK_FEATURES: Final = (
    "snow_depth_m",
    "snow_depth_change_24h",
    "snow_depth_change_72h",
    "snow_depth_change_7d",
    "snow_cover_fraction",
    "snow_cover_change_1d",
    "snow_cover_change_3d",
    "snow_cover_change_7d",
    "swe_mm",
    "swe_change_24h",
    "swe_change_72h",
    "new_snow_6h_cm",
    "new_snow_12h_cm",
    "new_snow_24h_cm",
    "new_snow_72h_cm",
    "new_snow_intensity_6h_cm_h",
    "snowfall_to_precip_24h",
    "snowpack_settlement_proxy",
    "snowmelt_24h",
    "snowmelt_72h",
    "solar_melt_proxy_24h",
    "snow_surface_temp_c",
    "snowpack_temp_gradient_proxy_c_m",
    "recent_avalanche_count_7d",
    "persistent_weak_layer_signal",
    "snowpack_stability_observation",
    "rain_on_snow_24h",
    "rain_on_snow_72h",
    "freeze_thaw_cycles_7d",
    "freeze_thaw_cycles_30d",
    "temp_min_24h",
    "temp_max_24h",
    "temperature_change_24h",
    "wind_speed_now_kmh",
    "wind_speed_max_24h_kmh",
    "wind_gust_max_24h_kmh",
    "wind_direction_mode_deg",
    "wind_direction_spread_deg",
    "wind_loading_proxy_24h",
    "wind_aspect_alignment_24h",
    "published_danger_rating_numeric",
)

FORECAST_FEATURES: Final = (
    "forecast_snowfall_0_6h",
    "forecast_snowfall_0_12h",
    "forecast_snowfall_0_24h",
    "forecast_snowfall_0_48h",
    "forecast_snowfall_0_72h",
    "forecast_max_snowfall_1h",
    "forecast_max_snowfall_3h",
    "forecast_max_snowfall_6h",
    "forecast_rain_0_6h",
    "forecast_rain_0_12h",
    "forecast_rain_0_24h",
    "forecast_rain_0_48h",
    "forecast_rain_0_72h",
    "forecast_temp_min",
    "forecast_temp_max",
    "forecast_wind_max_kmh",
    "forecast_gust_max_kmh",
    "forecast_wind_loading_proxy",
    "forecast_wind_aspect_alignment",
    "forecast_solar_melt_proxy",
    "forecast_rain_on_snow_72h",
    "forecast_freezing_level_min_m",
    "forecast_freezing_level_max_m",
    "forecast_snowfall_ensemble_mean",
    "forecast_snowfall_ensemble_p90",
    "forecast_snowfall_ensemble_p95",
    "forecast_snowfall_ensemble_spread",
    "forecast_exceedance_probability",
)

QUALITY_FEATURES: Final = (
    "dem_available",
    "static_snow_terrain_available",
    "snowpack_available",
    "snowpack_age_hours",
    "forecast_available",
    "forecast_age_hours",
    "weather_station_available",
    "feature_missing_fraction",
    "event_observation_coverage",
    "terrain_resolution_m",
    "weather_resolution_km",
)

MODEL_FEATURES: Final = (*STATIC_FEATURES, *SNOWPACK_FEATURES, *FORECAST_FEATURES, *QUALITY_FEATURES)

# The Rainier training corpus is small relative to the full contract and several optional
# features are entirely unavailable in that corpus.  This deliberately compact profile is the
# default production candidate: it keeps terrain geometry, observed loading, and the main
# forecast signals while avoiding high-variance optional fields.  It is a model feature profile,
# not a new API contract; inference still accepts every canonical feature and reads the subset
# recorded in the artifact metadata.
TRANSFERABLE_FEATURES: Final = (
    "elevation_mean",
    "slope_mean",
    "slope_max",
    "aspect_sin_mean",
    "aspect_cos_mean",
    "forest_fraction",
    "snow_ice_fraction",
    "snow_depth_m",
    "snow_depth_change_24h",
    "snow_depth_change_72h",
    "new_snow_24h_cm",
    "new_snow_72h_cm",
    "snowpack_settlement_proxy",
    "snow_surface_temp_c",
    "rain_on_snow_72h",
    "temp_min_24h",
    "temp_max_24h",
    "temperature_change_24h",
    "wind_speed_max_24h_kmh",
    "wind_gust_max_24h_kmh",
    "wind_loading_proxy_24h",
    "forecast_snowfall_0_24h",
    "forecast_snowfall_0_72h",
    "forecast_rain_0_24h",
    "forecast_rain_0_72h",
    "forecast_temp_min",
    "forecast_temp_max",
    "forecast_wind_max_kmh",
    "forecast_wind_loading_proxy",
    "forecast_rain_on_snow_72h",
    "forecast_snowfall_ensemble_p90",
    "forecast_snowfall_ensemble_spread",
)

FEATURE_PROFILES: Final = {
    "full": MODEL_FEATURES,
    "transferable": TRANSFERABLE_FEATURES,
}

CRITICAL_FEATURES: Final = (
    "slope_mean",
    "snowpack_available",
    "forecast_available",
)

REASON_CODES: Final = (
    "MODEL_ARTIFACT_MISSING",
    "CALIBRATION_MISSING",
    "STATIC_DATA_MISSING",
    "SNOWPACK_MISSING",
    "SNOWPACK_STALE",
    "FORECAST_UNAVAILABLE",
    "FORECAST_STALE",
    "WEATHER_DATA_MISSING",
    "LOW_DATA_QUALITY",
    "OUT_OF_DISTRIBUTION",
    "ABSTENTION_BAND",
    "HISTORICAL_INFERENCE_UNSUPPORTED",
    "TIMESTAMP_ALIGNMENT_ERROR",
)


def feature_groups() -> dict[str, tuple[str, ...]]:
    """Return JSON-safe feature groups for model metadata and documentation."""
    return {
        "static_terrain": STATIC_FEATURES,
        "snowpack_weather": SNOWPACK_FEATURES,
        "forecast": FORECAST_FEATURES,
        "quality": QUALITY_FEATURES,
    }


def features_for_profile(profile: str) -> tuple[str, ...]:
    """Return a validated model subset while retaining the canonical feature contract."""
    try:
        features = FEATURE_PROFILES[profile]
    except KeyError as error:
        raise ValueError(f"unknown avalanche feature profile: {profile}") from error
    validate_feature_names_subset(features)
    return features


def validate_feature_names_subset(names: list[str] | tuple[str, ...]) -> None:
    """Fail closed if a model references a feature outside the canonical contract."""
    extra = sorted(set(names) - set(MODEL_FEATURES))
    if extra:
        raise ValueError(f"avalanche feature profile contains unknown features: {extra}")


def validate_feature_names(names: list[str] | tuple[str, ...]) -> None:
    """Fail closed if a trained artifact uses a different feature contract."""
    if tuple(names) != MODEL_FEATURES:
        missing = sorted(set(MODEL_FEATURES) - set(names))
        extra = sorted(set(names) - set(MODEL_FEATURES))
        raise ValueError(f"avalanche feature contract mismatch; missing={missing}, extra={extra}")
