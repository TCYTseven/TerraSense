# ML agent guide

Offline Python for TerraSense: source downloads, the terrain feature table, the LightGBM susceptibility model, and map tiles. Track: ML and data. Nothing here runs as a server.

The production-oriented event-time classifier is a separate path from the legacy 30 m susceptibility
map. Its default prediction unit is a 1 km cell at a reference timestamp and its target is a
rainfall-triggered event in the next 72 hours. See `context/docs/production-risk.md`.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## Steps this folder owns

| Step | Script | Writes |
|---|---|---|
| 10 | `scripts/download_sources.py` | DEM and land cover in `data/raw/`, `data/seed/landslides.geojson`. Record each download in `data/seed/sources.md` by hand |
| 11 | `scripts/build_features.py` | `data/processed/features.parquet` |
| 12 | `scripts/train_susceptibility.py` | Legacy Rainier-only path (seven features). Superseded by `train_regional_susceptibility.py`; do not rerun on Rainier over the regional artifacts. |
| 12 (regional) | `scripts/download_region.py`, `scripts/build_regional_features.py`, `scripts/train_regional_susceptibility.py` | Regional DEM and land cover in `data/raw/`; regional labels and the Rainier-window stack in `data/processed/`; the calibrated model, `susceptibility_calibration.json`, `metrics.json`, feature importance, and `susceptibility.tif` on the legacy Rainier grid |
| 13, 18 | `scripts/render_tiles.py` | XYZ PNGs in `backend/tiles/`. The API renders the probability layer itself on each run (`backend/app/assessment.py`) |
| 14 | `scripts/import_trails.py` | `data/seed/trails.geojson`, `data/seed/trail_segments.geojson` (the hero trail's mile segments), and the walkable network cache in `data/raw/` |
| 17 | `backend/app/ml/model_b.py` | Live 72-hour probability from susceptibility plus Open-Meteo rain. `backend/app/ml/probability.py` calls `run(rain)` and reads `.probability`, `.transform`, and `.crs` from the result; until the module exists the heat map is the susceptibility stand-in |
| 39 | `scripts/build_hill_window.py` | Turtle Mountain's own DEM and WorldCover window, scored with the existing LightGBM and Model B. Does not retrain or replace Rainier's rasters |
| 19 | `scripts/build_trail_network.py` | `data/seed/trail_network.geojson`: the walkable network around the hero loop, with elevations. `backend/app/bypass.py` routes the bypass on it during each run |

## Layout

- `scripts/`: one script per step. Run each from the repo root, for example `python ml/scripts/download_sources.py`.
- `artifacts/`: model file, `metrics.json`, feature importance. `*.tif` here is gitignored.

## Rules

- Use the shared bounding box `[-121.93, 46.76, -121.54, 46.96]` as a named constant.
- Downloads go to `data/raw/`. Derived rasters and tables go to `data/processed/`. Both are gitignored. Small files the app needs go to `data/seed/`.
- Record every download's URL and access date in `data/seed/sources.md`.
- Resample every layer to one 30 m grid before building features.
- Split train and test by space, using the region column. Never shuffle pixels across the box.
- The regional model never trains on the Rainier box or its 2 km buffer. Hyperparameters and the calibrator come from inner block CV on training folds only; thresholds are the shared bin edges, never picked on test data.
- Judge a terrain change by leave-one-region-out metrics (`geo_validate.py`), not spatial CV alone. Never tune on the Rainier rows; `geo_validate.py` scores them once, after its selection rule has run. Thresholds and calibrators come from inner validation rows only. Report prevalence and lift with every PR-AUC.
- Publish the AUC you measure in `artifacts/metrics.json`. 0.85 is not a gate. Until landslide labels exist, `metrics.json` says `trained: false` and `auc: null`: never present the knowledge-driven index as a trained model.
- Tiles are XYZ PNG in EPSG:3857 so they sit on the map's 3D terrain.
- Model B weights are named constants with a comment on each.

## Environment

Run from the repo root:

```bash
python3.12 -m venv ml/.venv && source ml/.venv/bin/activate
pip install -r ml/requirements.lock.txt  # verified deployment environment
# Or use the flexible direct requirements during development:
# pip install -r ml/requirements.txt -r ml/requirements-dev.txt
python ml/scripts/download_sources.py      # step 10: DEM, land cover, landslide points
python ml/scripts/build_features.py        # step 11: 30 m feature stack, labeled table when points exist
python ml/scripts/build_static_features.py # production path: aggregate static inputs to 1 km cells
python ml/scripts/train_susceptibility.py  # step 12 (legacy): Rainier-only LightGBM; do not rerun over the regional artifacts
python ml/scripts/download_region.py                 # regional DEM + WorldCover windows (~65 MB, ~45 s)
python ml/scripts/build_regional_features.py         # 17-band regional stack, USGS v3 labels, Rainier window (~45 s)
python ml/scripts/train_regional_susceptibility.py   # nested spatial CV, external Rainier test, calibrated map (~3 min)
python ml/scripts/render_tiles.py          # step 13: backend/tiles/susceptibility/{z}/{x}/{y}.png
python ml/scripts/geo_validate.py        # step 35: leave-one-region-out validation, ablation, shift, errors (~6 min)
python ml/scripts/combined_validate.py   # step 35: terrain x rain index on dated events (~2.5 min)
python ml/scripts/validate_pipeline.py --require-probability  # read-only deployment audit
python ml/scripts/build_risk_samples.py --dynamic data/raw/normalized/hourly.parquet --out data/processed/risk_samples.parquet
python ml/scripts/build_risk_dataset.py --samples data/processed/risk_samples.parquet --out data/processed/landslide_risk.parquet
python ml/scripts/train_risk_model.py --table data/processed/landslide_risk.parquet
python ml/scripts/event_catalog.py         # Model B check: dated rain-triggered events -> clusters (~4 s)
python ml/scripts/event_rain.py            # archive weather + case-crossover features (cached; first run ~30 min)
python ml/scripts/event_validate.py        # metrics, CIs, fitted weights -> artifacts/model_b_validation.json
python ml/scripts/import_trails.py         # step 14: OpenStreetMap trails via Overture, the hero trail's segments
python ml/scripts/build_trail_network.py  # step 19: the network the bypass routes on (needs step 14's cache and the DEM)
```

Each download is recorded in `data/seed/sources.md`. The landslide stage needs a network that reaches data.nasa.gov, or a hand-downloaded CSV passed with `--glc-csv`.
