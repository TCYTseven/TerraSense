"""Shared contract for the production-oriented 72-hour landslide classifier.

This module intentionally has no FastAPI, database, raster, or model-library imports.  The
offline builders and the API both use these names so a training table and a live request cannot
quietly drift apart.
"""

from __future__ import annotations

from typing import Final, Literal

PredictionState = Literal["HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"]

PREDICTION_HORIZON_HOURS: Final = 72
DEFAULT_CELL_SIZE_M: Final = 1000
DEFAULT_TARGET_PRECISION: Final = 0.85
DEFAULT_HARD_NEGATIVE_FRACTION: Final = 0.40
DEFAULT_SUSCEPTIBLE_NEGATIVE_FRACTION: Final = 0.30
DEFAULT_MIN_DATA_QUALITY: Final = 0.80
DEFAULT_OOD_THRESHOLD: Final = 0.35
DEFAULT_ABSTENTION_BAND: Final = 0.05

PREDICTION_STATES: Final = ("HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN")

# Static groups. These names are deliberately aggregate-safe: the prediction unit is a 1 km
# cell, even when the source raster is 30 m.
STATIC_FEATURES: Final = (
    "elevation_mean",
    "elevation_std",
    "slope_mean",
    "slope_max",
    "slope_p90",
    "aspect_sin_mean",
    "aspect_cos_mean",
    "profile_curvature_mean",
    "plan_curvature_mean",
    "roughness_mean",
    "terrain_ruggedness_mean",
    "local_relief_100m",
    "local_relief_500m",
    "local_relief_1km",
    "twi_mean",
    "flow_accumulation_mean",
    "dist_drainage_mean",
    "forest_fraction",
    "shrub_fraction",
    "grassland_fraction",
    "cropland_fraction",
    "built_fraction",
    "bare_fraction",
    "water_fraction",
    "snow_ice_fraction",
    "soil_clay_0_30",
    "soil_sand_0_30",
    "soil_silt_0_30",
    "soil_bulk_density_0_30",
    "soil_coarse_fragments_0_30",
    "soil_organic_carbon_0_30",
    "road_distance_m",
    "road_density_km_km2",
    "major_road_density_km_km2",
    "geology_class_encoded",
    "fault_distance_m",
)

PAST_RAIN_FEATURES: Final = (
    "rain_30m",
    "rain_1h",
    "rain_3h",
    "rain_6h",
    "rain_12h",
    "rain_24h",
    "rain_48h",
    "rain_72h",
    "rain_7d",
    "rain_14d",
    "rain_30d",
    "max_30m_intensity_24h",
    "max_1h_intensity_24h",
    "max_3h_intensity_72h",
    "max_6h_intensity_72h",
    "rain_last_6h_vs_prev_6h",
    "rain_acceleration",
    "consecutive_wet_hours",
    "hours_since_heavy_rain",
    "hours_since_rain_started",
    "rain_24h_percentile",
    "rain_72h_percentile",
    "rain_7d_percentile",
    "rain_24h_anomaly",
    "rain_72h_anomaly",
)

HYDROLOGY_FEATURES: Final = (
    "surface_soil_moisture",
    "root_zone_soil_moisture",
    "soil_moisture_24h",
    "soil_moisture_72h",
    "soil_moisture_7d",
    "soil_moisture_change_24h",
    "soil_moisture_change_72h",
    "soil_moisture_percentile",
    "soil_moisture_anomaly",
    "era5_soil_water_24h",
    "era5_soil_water_72h",
    "era5_soil_water_7d",
    "runoff_24h",
    "runoff_72h",
    "runoff_7d",
    "evapotranspiration_24h",
    "water_balance_72h",
)

SNOW_FEATURES: Final = (
    "snow_depth",
    "snowmelt_24h",
    "snowmelt_72h",
    "snow_fraction",
    "snow_fraction_change_1d",
    "snow_fraction_change_3d",
    "snow_fraction_change_7d",
    "rapid_snow_loss_flag",
    "rain_on_snow_flag",
    "rain_on_snow_intensity",
    "snowmelt_plus_rain_24h",
    "snowmelt_plus_rain_72h",
    "temp_min_24h",
    "temp_max_24h",
    "freeze_thaw_cycles_7d",
    "freeze_thaw_cycles_30d",
    "temperature_crossed_freezing_24h",
)

FORECAST_FEATURES: Final = (
    "forecast_rain_0_6h",
    "forecast_rain_0_12h",
    "forecast_rain_0_24h",
    "forecast_rain_0_48h",
    "forecast_rain_0_72h",
    "forecast_max_1h_rain",
    "forecast_max_3h_rain",
    "forecast_max_6h_rain",
    "forecast_peak_rain_timing_h",
    "forecast_temperature_min",
    "forecast_temperature_max",
    "forecast_snowmelt_proxy",
    "forecast_precip_ensemble_mean",
    "forecast_precip_p90",
    "forecast_precip_p95",
    "forecast_precip_ensemble_spread",
    "forecast_exceedance_probability",
)

QUALITY_FEATURES: Final = (
    "imerg_age_minutes",
    "smap_age_hours",
    "era5_age_hours",
    "gfs_forecast_age_hours",
    "dem_available",
    "soilgrids_available",
    "worldcover_available",
    "smap_available",
    "smap_quality_flag",
    "forecast_available",
    "feature_missing_fraction",
)

MODEL_FEATURES: Final = (
    *STATIC_FEATURES,
    *PAST_RAIN_FEATURES,
    *HYDROLOGY_FEATURES,
    *SNOW_FEATURES,
    *FORECAST_FEATURES,
    *QUALITY_FEATURES,
)

CRITICAL_QUALITY_FEATURES: Final = (
    "dem_available",
    "forecast_available",
    "feature_missing_fraction",
)

REASON_CODES: Final = (
    "MODEL_ARTIFACT_MISSING",
    "CALIBRATION_MISSING",
    "FORECAST_UNAVAILABLE",
    "WEATHER_FEED_UNAVAILABLE",
    "ESTIMATE_UNAVAILABLE",
    "FORECAST_STALE",
    "STATIC_DATA_MISSING",
    "SOIL_DATA_MISSING",
    "SMAP_MISSING",
    "ERA5_LAND_MISSING",
    "OBSERVATION_STALE",
    "LOW_DATA_QUALITY",
    "OUT_OF_DISTRIBUTION",
    "ABSTENTION_BAND",
    "ENSEMBLE_DISAGREEMENT",
    "HISTORICAL_INFERENCE_UNSUPPORTED",
    "TIMESTAMP_ALIGNMENT_ERROR",
)


def feature_groups() -> dict[str, tuple[str, ...]]:
    """JSON-safe feature groups for model cards and API responses."""
    return {
        "static": STATIC_FEATURES,
        "past_rain": PAST_RAIN_FEATURES,
        "hydrology": HYDROLOGY_FEATURES,
        "snow": SNOW_FEATURES,
        "forecast": FORECAST_FEATURES,
        "quality": QUALITY_FEATURES,
    }


def validate_feature_names(names: list[str] | tuple[str, ...]) -> None:
    """Fail closed when an artifact was trained with a different feature contract."""
    if tuple(names) != MODEL_FEATURES:
        missing = sorted(set(MODEL_FEATURES) - set(names))
        extra = sorted(set(names) - set(MODEL_FEATURES))
        raise ValueError(f"risk feature contract mismatch; missing={missing}, extra={extra}")
