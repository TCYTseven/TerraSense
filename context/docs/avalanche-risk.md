# Avalanche-risk model

TerraSense now has a parallel avalanche-risk model path. It does not alter the landslide model,
its labels, its score, or its API.

## Target

The default target is:

> `P(avalanche occurrence or release in a 1 km cell during the next 24 hours | information available at T)`

The horizon is intentionally shorter than the landslide model's 72 hours because avalanche
instability can change quickly after new snow, wind loading, rain-on-snow, or rapid warming.

`HIGH_RISK`, `NOT_HIGH_RISK`, and `UNCERTAIN` are model decision states, not official avalanche
danger ratings. The API does not translate them into a North American Avalanche Danger Scale
rating without a separately validated danger-rating dataset.

## Feature groups

Static terrain features describe release and runout context: elevation, slope bands (including
the 30–45 degree starting-zone band), aspect, curvature, roughness, local relief, terrain traps,
flow accumulation, drainage proximity, forest, and snow/ice cover.

Dynamic features describe the snowpack and its loading state: snow depth and SWE where available,
new snow at several windows, snow-depth/SWE change, snow cover change, snowmelt, rain-on-snow,
freeze-thaw, temperature transitions, wind speed/gust/direction, wind loading, and wind/aspect
alignment. Optional field-report features include recent avalanche activity, persistent weak-layer
signals, snowpack stability observations, and published danger ratings.

Forecast features include snowfall, rain, temperature, wind/gusts, freezing-level bounds, rain on
snow, and ensemble snowfall spread/exceedance probabilities. Forecast initialization must be no
later than the reference time.

## Recommended data sources

- Avalanche labels: [CAIC observations and Avalanche Explorer](https://avalanche.state.co.us/observations)
  and [NWAC observations](https://nwac.us/observations/). These catalogs are valuable but not
  complete inventories, so a missing report is not a certain negative.
  `download_avalanche_regional_catalog.py` now caches a bounded Northwest catalog for future
  external validation: 1,282 avalanche observations and 6,255 date-filtered field reports from
  2023-10-25 through 2026-07-20. It is intentionally audit-only until each record receives
  leakage-safe terrain and as-of weather/forecast features.
  `download_caic_avalanche_data.py` also caches the official CAIC Avalanche Explorer observation
  feed across a configurable historical interval. CAIC records include event time, coordinates,
  aspect, elevation, slope, trigger, size, and problem type, which are useful for a cross-region
  transfer set. They remain audit-only until paired with the same static terrain and as-of
  forecast feature path; CAIC's public API is not treated as a complete no-event inventory.
  With `--include-controls`, the downloader also retains reports with zero observed avalanches
  as coverage-backed controls. These are eligible controls only after their nested observation
  coordinate and as-of timestamp are joined; they are not universal negatives.
- Snowpack observations: [NRCS AWDB/SNOTEL](https://www.nrcs.usda.gov/programs-initiatives/sswsf-snow-survey-and-water-supply-forecasting-program/snow-and-water-products)
  for SWE, snow depth, precipitation, temperature, and station quality.
- Forecasts: NOAA [GFS](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast)
  and GEFS retrospective/operational products for precipitation type, snowfall, temperature,
  wind, freezing level, and ensemble spread. Historical GEFS cycles are available from the
  [NOAA AWS Open Data bucket](https://registry.opendata.aws/noaa-gefs/) and are fetched with
  `ml/scripts/download_noaa_historical_forecasts.py` using `.idx` byte ranges.
- Terrain: the existing Copernicus DEM and WorldCover path. Add a snow-specific MODIS/SNODAS
  adapter when its acquisition and quality metadata are available.
- Compatibility weather: Open-Meteo may be used for fixtures and development, but the live
  avalanche endpoint requires a source identified as GFS or GEFS before it can make a classified
  answer.

## Reproducible commands

From the repository root:

```bash
ml/.venv/bin/python ml/scripts/build_avalanche_dataset.py \
  --dynamic data/raw/normalized/avalanche_hourly.parquet \
  --events data/raw/avalanche/occurrences.csv \
  --static data/processed/static/static_cells.parquet \
  --out data/processed/avalanche_risk.parquet

ml/.venv/bin/python ml/scripts/download_noaa_historical_forecasts.py \
  --variables apcp,weasd,tmp2m,ugrd10m,vgrd10m \
  --out data/processed/avalanche_noaa_gefs_all_forecasts.parquet

ml/.venv/bin/python ml/scripts/download_caic_avalanche_data.py \
  --start-date 2013-10-01 \
  --include-controls \
  --out-dir data/raw/avalanche/caic

ml/.venv/bin/python ml/scripts/prepare_nwac_avalanche_dataset.py \
  --forecast data/processed/avalanche_noaa_gefs_all_forecasts.parquet \
  --out data/processed/avalanche_nwac_gefs_all.parquet

ml/.venv/bin/python ml/scripts/train_avalanche_model.py \
  --table data/processed/avalanche_risk.parquet \
  --artifacts ml/artifacts/avalanche

ml/.venv/bin/python ml/scripts/benchmark_avalanche_models.py \
  --table data/processed/avalanche_nwac_gefs_all.parquet \
  --out ml/artifacts/avalanche/nwac_gefs_all/model_benchmark_v2.json

ml/.venv/bin/python ml/scripts/train_avalanche_model.py \
  --table data/processed/avalanche_nwac_gefs_all.parquet \
  --feature-profile transferable \
  --train-end-year 2024 \
  --calibration-year 2025 \
  --artifacts ml/artifacts/avalanche/nwac_gefs_transferable_v2

ml/.venv/bin/python ml/scripts/evaluate_avalanche_temporal.py \
  --table data/processed/avalanche_nwac_gefs_all.parquet \
  --feature-profile transferable \
  --out ml/artifacts/avalanche/nwac_gefs_transferable_v2/temporal_evaluation.json
```

The builder rejects future feature timestamps and forecast runs initialized after the reference
time. The trainer uses a deterministic geographic/temporal holdout, fits calibration only on the
validation fold, reports prevalence beside PR-AUC, and leaves the high-risk threshold unset when
the requested precision is not supported. A missing avalanche report is not a negative label:
the builder marks those rows `unknown_absence` and the trainer excludes them by default. A sample
becomes an eligible negative only when its observation-coverage field is at least 0.80. The
`AVALANCHE_MIN_NEGATIVE_COVERAGE` environment variable or `--min-negative-coverage` CLI option
controls that floor. The `--allow-unknown-absence` flag exists for explicitly exploratory analyses
and must not be used for operational evaluation.

## API

```text
POST /api/v1/avalanche-risk
{
  "latitude": 46.8523,
  "longitude": -121.7603
}
```

The response includes the 24-hour window, probability when a calibrated artifact is available,
confidence interval, data-quality score, OOD score, reason codes, snowpack summary, model drivers,
and source provenance. Missing artifacts, missing snowpack, stale forecasts, or out-of-domain
conditions return `UNCERTAIN`.

Numeric API headline probabilities are floored at `0.10` (`MIN_REPORTED_HAZARD_PROBABILITY`).
The exact calibrated value remains available as `calibrated_probability` and is used for the
state, threshold, calibration, and evaluation decisions; a missing/uncertain prediction remains
`null` rather than being fabricated as 10%.

The API reads `AVALANCHE_ARTIFACT_DIR` when set (relative paths resolve from the repository root),
so a separately reviewed artifact can be exercised without replacing the default fail-closed
artifact directory. Do not point it at `nwac_gefs` for public warnings without adding external
regions, optional forecast variables, and an operational validation review.

## Current benchmark and limitation

The repository contains the original Rainier NWAC observed-weather proxy under
`ml/artifacts/avalanche/nwac_observed_proxy/`, the full forecast-aware diagnostic under
`ml/artifacts/avalanche/nwac_gefs_all/`, and a compact transfer-oriented candidate under
`ml/artifacts/avalanche/nwac_gefs_transferable_v2/`. The benchmark selects candidates only on the
2025 calibration year, then reports 2026 once as an untouched test:

| Candidate | 2026 ROC-AUC | 2026 PR-AUC | PR lift vs 0.432 baseline | Brier | ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| slope-only | 0.585 | 0.504 | 1.17x | — | — |
| full LightGBM | 0.703 | 0.631 | 1.46x | 0.253 | 0.219 |
| transferable 32-feature LightGBM | **0.716** | **0.659** | **1.53x** | **0.229** | **0.120** |

The compact candidate uses the 32 terrain, observed-loading, and forecast variables that are
available in the training domain; it removes all-missing and high-variance optional fields from
the model input without changing the canonical API feature contract. Its 2025-only threshold for
85% precision was 0.586; on untouched 2026 it produced 66.7% precision and 10.5% recall. That
failed the requested precision target, so there is still no validated high-risk operating point.
The calibrated model is a candidate for further review, not an operational warning model.

The historical forecast-access bottleneck is resolved: all 173 rows have dated as-of GEFS inputs.
The historical forecast-access bottleneck is resolved: all 173 rows have dated as-of GEFS inputs.
The regional observation corpus is now acquired, but the main remaining limitation is target-domain
validity: only one geographic region has fully joined terrain + snowpack + forecast features, with
70 positive cell-days and coverage-backed local negatives. The 1,282 regional observations cannot
be used as training rows yet without joining the corresponding static terrain and as-of weather;
doing so would create an inconsistent feature domain. External-region feature construction and a
larger systematic event/control sample are required before deployment. Do not treat these
diagnostic results as operational avalanche forecast accuracy.

This model is a research prototype and is not a replacement for official avalanche forecasts,
professional snowpack assessment, or local emergency-management guidance.
