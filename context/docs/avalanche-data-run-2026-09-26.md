# Rainier avalanche data run — 2026-09-26

This report records the first real-data execution of the avalanche pipeline. It is intentionally
not a deployment-readiness claim.

## Data acquired

- NWAC/National Avalanche Center public API, Rainier bounding box: 81 avalanche observation
  records and 281 general field observations covering 2023-10-26 through 2026-07-19.
- After mapping to the 1 km static grid and collapsing duplicate same-cell/same-day reports:
  70 positive sample cell-days and 103 coverage-backed negative cell-days were built.
- Open-Meteo hourly retrospective weather at a Rainier-area grid point: 24,000 hourly records
  from 2023-10-25 through 2026-07-20. The feature generator uses only values at or before T.
- NRCS Paradise SNOTEL station 679 hourly report: 23,959 parsed hourly rows with station SWE
  and snow-depth values. These are joined as-of T and used as a station-level snowpack proxy.
- Existing static inputs: Copernicus DEM/terrain aggregates, ESA WorldCover, and the current
  Rainier static-cell table.
- A bounded Northwest Avalanche.org/National Avalanche Center catalog was also cached for future
  external validation: 1,282 avalanche observations and 6,255 field reports within the requested
  2023-10-25 through 2026-07-20 window across `-125,42,-116,49.1`. The API returned 329 field
  records outside the requested date range; those were excluded before writing the filtered raw
  pages. This regional corpus is not silently mixed into training because its static and as-of
  weather features have not been joined yet.
- The official CAIC Avalanche Explorer observation API was queried separately for historical
  event labels. It is reproducible through `download_caic_avalanche_data.py` and stores raw pages
  plus normalized records. CAIC adds independent multi-year labels and event attributes, but it
  is intentionally not mixed into the Rainier training table until matching terrain, snowpack,
  and as-of GEFS features are available.
- Historical NOAA GEFS access is now wired through the public AWS Open Data bucket. The full
  backfill used 119 completed as-of cycles from 2023-10-25 18Z through 2026-05-03 18Z, 52 Rainier
  cells, and 12 six-hour forecast intervals per reference. It fetched 7,506 indexed byte-range
  requests plus 10,829 cache hits (about 3.87 GB of GRIB2 slices) with zero failed reference/
  lead groups. GEFS precipitation mean/spread, snow-water-equivalent change, 2 m temperature,
  and 10 m wind features are now all available through the same downloader.

Raw acquisition files are under `data/raw/avalanche/` and are ignored by Git. The exact NWAC
queries and weather URL are in `data/raw/avalanche/manifest.json` after running the downloader.

## Leakage and label controls

- The current-day avalanche is not included in `recent_avalanche_count_7d`; only events strictly
  before T are eligible.
- Positive and negative rows receive the same coverage value. Coverage is not allowed to encode
  the label.
- Negative rows require a field observation whose `avalanches_observed` flag is false. An absent
  catalog report is not used as a negative.
- No future observed weather is passed to the feature generator.
- Forecast features are left missing rather than filled with future observed weather. The new
  forecast-aware table has `forecast_available = 1` for all 173 labeled rows, and the rain,
  snowfall, temperature, wind, and GEFS snowfall-uncertainty feature groups are populated from
  an as-of GEFS cycle.

## Honest train/calibration/test result

The primary result uses complete calendar years:

- training: 2023–2024, 90 rows / 37 positives;
- calibration: 2025, 39 rows / 14 positives;
- untouched test: 2026, 44 rows / 19 positives;
- test prevalence and random/no-skill PR baseline: **0.4318**.

| Model / split | ROC-AUC | PR-AUC | PR lift | Brier | ECE |
|---|---:|---:|---:|---:|---:|
| LightGBM raw, 2026 test | **0.691** | **0.609** | **1.41x** | **0.256** | 0.237 |
| LightGBM + isotonic calibration, 2026 test | 0.589 | 0.472 | 1.09x | 0.288 | **0.193** |
| transferable 32-feature LightGBM + Platt, 2026 test | **0.716** | **0.659** | **1.53x** | **0.229** | **0.120** |
| slope-only logistic baseline, 2026 test | 0.585 | 0.504 | 1.17x | — | — |
| random/no-skill PR baseline | — | 0.432 | 1.00x | — | — |

Forecast-access comparison on the same untouched 2026 year split:

| Feature table | ROC-AUC | PR-AUC | PR lift | Brier | ECE |
|---|---:|---:|---:|---:|---:|
| Observed-weather proxy | 0.691 | 0.609 | 1.41x | 0.256 | 0.237 |
| GEFS precipitation mean/spread added | 0.686 | 0.609 | 1.41x | 0.264 | 0.265 |
| GEFS rain + snow + temperature + wind | **0.703** | **0.631** | **1.46x** | **0.253** | **0.219** |

The access problem is fixed in the data path. Adding all four forecast driver groups improves the
untouched ranking modestly over the observed-weather proxy (+0.013 ROC-AUC, +0.022 PR-AUC), but
the compact transfer-oriented profile improves it further in this holdout (+0.025 ROC-AUC,
+0.050 PR-AUC versus the previous full model). The sample is still too small to treat that
difference as stable deployment evidence.

The transferable model's target 85% precision threshold selected on the 2025 calibration year was
0.586. Applied once to the untouched 2026 test year it produced precision 0.667 and recall 0.105,
so it did not meet the target and there is currently no validated high-risk operating point. This
is an abstention/insufficient-evidence result, not a reason to lower the threshold on the test set.

## Interpretation

The pipeline executes end-to-end on real Rainier avalanche observations and shows weak-to-moderate
ranking signal above the no-skill PR baseline. The compact feature profile reduces overfitting
relative to the full 106-column contract. Platt calibration on the 39-row validation year improves
the held-out Brier/ECE, while isotonic calibration achieves perfect in-sample validation ECE but
degrades the untouched test ranking and Brier; isotonic is therefore not selected automatically
for this small sample.
Prevalence is unusually high for a field-observation sample, and there is only one geographic
region. The result should be treated as a data/pipeline validation, not as an accurate operational
avalanche forecast model.

The historical forecast-alignment bottleneck is resolved: all 173 rows now have a dated, as-of
GEFS run and all implemented forecast driver groups. The remaining bottleneck is target-domain
validity: one Rainier region, only 70 positive event cell-days, coverage-backed local negatives,
and no external-region avalanche holdout. Rolling-origin testing is also unstable because the
earliest fold has only 19 training rows. The live API remains fail-closed until external
validation and a larger systematic event/control dataset are available.

## Reproduce

```bash
ml/.venv/bin/python ml/scripts/download_nwac_avalanche_data.py
ml/.venv/bin/python ml/scripts/prepare_nwac_avalanche_dataset.py \
  --out data/processed/avalanche_nwac_observed_proxy.parquet
ml/.venv/bin/python ml/scripts/download_noaa_historical_forecasts.py \
  --variables apcp,weasd,tmp2m,ugrd10m,vgrd10m \
  --out data/processed/avalanche_noaa_gefs_all_forecasts.parquet
ml/.venv/bin/python ml/scripts/prepare_nwac_avalanche_dataset.py \
  --forecast data/processed/avalanche_noaa_gefs_all_forecasts.parquet \
  --out data/processed/avalanche_nwac_gefs_all.parquet
ml/.venv/bin/python ml/scripts/train_avalanche_model.py \
  --table data/processed/avalanche_nwac_gefs_all.parquet \
  --artifacts ml/artifacts/avalanche/nwac_gefs_all
ml/.venv/bin/python ml/scripts/evaluate_avalanche_temporal.py \
  --table data/processed/avalanche_nwac_gefs_all.parquet \
  --out ml/artifacts/avalanche/nwac_gefs_all/temporal_evaluation.json
```

The trainer's built-in latest-year report is a useful pipeline diagnostic. The metrics above use
the stricter three-way split and are the numbers to cite for this run. The `nwac_observed_proxy`
artifact must not be placed in the default live-artifact directory because it has no historical
forecast features.
