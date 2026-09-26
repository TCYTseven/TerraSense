# Production 72-hour landslide risk

TerraSense now has a separate event-time classifier contract alongside the existing HackGT map and agent workflow.

## Prediction unit

The production unit is a configurable metric cell (default 1,000 m) at a reference timestamp `T`:

`P(rainfall-triggered landslide in this cell during [T, T + 72 hours] | information available at T)`

The 30 m DEM remains an input source. It does not imply that the output is accurate to 30 m.

## Data path

`ml/scripts/risk_sources.py` is the source registry and cache/checksum primitive. The supported source families are:

- dated NASA COOLR/Global Landslide Catalog and USGS Inventories v3 labels;
- Copernicus DEM, SoilGrids, ESA WorldCover, OpenStreetMap, and optional geology for static susceptibility;
- NASA GPM IMERG V07, NASA SMAP L4, and ERA5-Land for historical state;
- NOAA GFS and GEFS reforecast products for operational and retrospective forecast features;
- MODIS Terra/Aqua snow products for snow cover and snow-loss signals.

Provider-specific raw products must be normalized into the hourly table contract before feature assembly. Credentialed downloads are explicit and cached; a failed download is never represented as a successful source.

`ml/scripts/build_static_features.py` aggregates the existing terrain stack into 1 km metric cells,
computes cell-level terrain and WorldCover fractions, and accepts optional SoilGrids rasters. Its
JSON sidecar is the backend's dependency-light runtime artifact; missing SoilGrids, roads, or
geology remain null and are visible to the quality gate.

## Leakage controls

`ml/scripts/build_risk_samples.py` emits rows with `reference_timestamp`, `feature_asof`, and forecast initialization. `build_risk_dataset.py` accepts the NASA GLC CSV export or NASA/USGS-style GeoJSON, filters rainfall-related triggers, preserves source IDs/links and ingestion timestamps, rejects observed data after `T`, forecasts initialized after `T`, undated events, and event records outside the configured timestamp uncertainty. A configurable location-confidence floor is available. Storm/event groups and spatial groups stay together during evaluation.

## Model and decision states

`ml/scripts/train_risk_model.py` trains a LightGBM baseline, calibrates held-out scores with isotonic regression or Platt scaling, measures PR-AUC/ROC-AUC/Brier/ECE, and selects the lowest threshold that reaches the configured target precision. If validation cannot support that target, the threshold is null.

`ml/scripts/backtest_risk_model.py` replays a canonical historical table with the persisted model
and calibration, emits per-row three-state outputs, subgroup metrics, and grouped bootstrap
intervals. It labels the result `operational_realism_constrained` only when the table's as-of
checks pass; it cannot recreate provider dissemination latency or historical product revisions.

The API is `POST /api/v1/landslide-risk`. It returns:

- `HIGH_RISK` only when calibrated probability clears the validated threshold and quality/OOD gates pass;
- `NOT_HIGH_RISK` only when the model is in-domain and the inputs are sufficiently complete;
- `UNCERTAIN` for missing calibration, stale/unavailable forecasts, missing critical static data, OOD features, disagreement, or the threshold abstention band.

Alongside the state, every in-domain answer carries the number to show:

- `probability`: 0 to 1. The calibrated probability when a calibrated model exists (`probability_source: "calibrated_classifier"`). Until then, the Model B estimate at the clicked 30 m pixel (`"model_b_estimate"`): the same Model B that draws the heat layer, on today's rain. The rendered tiles refresh on **Analyze now**, so they can lag the card when the rain has changed since the last run. A pixel the map leaves blank gets `null` and `ESTIMATE_UNAVAILABLE`.
- Rain: every click in the study box is scored on the one trail-zone Open-Meteo series the heat map uses (Paradise, 1,650 m), not a per-click fetch. A calibrated model trained on per-cell rain would need that call changed back.
- `risk_level`: the shared bin for that probability (low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7).
- `estimate`: the Model B method, the pixel value, the 1 km cell's mean, max, and share at high or above, the rain totals against their Guzzetti thresholds, and each input's logit term (terrain, forecast rain, antecedent moisture) with whether it raises or lowers the estimate, and `validation`: held-out ROC-AUC with 95% intervals for terrain (10 km spatial blocks in the western Cascades, and the Rainier box's own mapped slides) and for the rain trigger (767 dated landslides, whole water years held out), read from `ml/artifacts/metrics.json` and `ml/artifacts/model_b_validation.json`.

The estimate is a relative 72-hour risk index, not an absolute probability: its level depends on the case-control sampling ratios behind both fits. It never changes `state`. It is `null`, never a dry-day guess, when rain data is unavailable (`WEATHER_FEED_UNAVAILABLE`), when the terrain raster is missing or the pixel is blank (`ESTIMATE_UNAVAILABLE`), or outside the study box. The agents' `production_72h_classification` fact leaves the point estimate out: at the summit it is one pixel, and the map summary and hazard zone already carry the map.

The endpoint is intentionally returning `UNCERTAIN` in the checked-in repository until a real timestamped multi-year feature table and calibrated artifact are built. The current Rainier NASA export has historical points, but its four events are not all rainfall-trigger labels; the existing seed remains available for historical display and the new builder filters labels conservatively.

## Reproduction

```bash
# Install the checked-in ML environment and backend runtime.
ml/.venv/bin/python -m pip install -r ml/requirements.lock.txt
backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Cache an explicitly supplied source and record its checksum.
ml/.venv/bin/python ml/scripts/download_risk_source.py gfs \
  --url '<NOAA product URL>' --out data/raw/gfs/example.grib2

# Aggregate the 30 m terrain source into the 1 km static prediction unit.
ml/.venv/bin/python ml/scripts/build_static_features.py \
  --stack data/processed/features.tif \
  --out data/processed/static/static_cells.parquet \
  --json-out data/processed/static/static_cells.json

# Normalize provider products into a wide hourly table, then assemble samples.
ml/.venv/bin/python ml/scripts/build_risk_samples.py \
  --dynamic data/raw/normalized/hourly.parquet \
  --static data/processed/static_cells.parquet \
  --out data/processed/risk_samples.parquet

# Join verified event labels and train/calibrate/select the high-risk threshold.
ml/.venv/bin/python ml/scripts/build_risk_dataset.py \
  --samples data/processed/risk_samples.parquet \
  --labels data/seed/landslides.geojson \
  --labels /path/to/Global_Landslide_Catalog_Export_rows.csv \
  --minimum-location-confidence 2 \
  --out data/processed/landslide_risk.parquet
ml/.venv/bin/python ml/scripts/train_risk_model.py \
  --table data/processed/landslide_risk.parquet \
  --artifacts ml/artifacts
ml/.venv/bin/python ml/scripts/backtest_risk_model.py \
  --table data/processed/landslide_risk.parquet \
  --artifacts ml/artifacts
```

This system estimates rainfall-triggered landslide risk. It is not a replacement for official emergency-management warnings, geotechnical investigation, or local authorities.
