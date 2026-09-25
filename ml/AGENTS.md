# ML agent guide

Offline Python for TerraSense: source downloads, the terrain feature table, the LightGBM susceptibility model, and map tiles. Track: ML and data. Nothing here runs as a server.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## Steps this folder owns

| Step | Script | Writes |
|---|---|---|
| 10 | `scripts/download_sources.py` | DEM and land cover in `data/raw/`, `data/seed/landslides.geojson`, `data/seed/sources.md` |
| 11 | `scripts/build_features.py` | `data/processed/features.parquet` |
| 12 | `scripts/train_susceptibility.py` | Model, `artifacts/metrics.json`, feature importance, susceptibility GeoTIFF |
| 13, 18 | `scripts/render_tiles.py` | XYZ PNGs in `backend/tiles/` |
| 14 | Trail import | `data/seed/trails.geojson`, trail segments |
| 17 | `backend/app/ml/model_b.py` | Live 72-hour probability from susceptibility plus Open-Meteo rain |
| 19 | Bypass | One bypass line that avoids the worst segment |

## Layout

- `scripts/`: one script per step. Run each from the repo root, for example `python ml/scripts/download_sources.py`.
- `artifacts/`: model file, `metrics.json`, feature importance. `*.tif` here is gitignored.

## Rules

- Use the shared bounding box `[-121.93, 46.76, -121.54, 46.96]` as a named constant.
- Downloads go to `data/raw/`. Derived rasters and tables go to `data/processed/`. Both are gitignored. Small files the app needs go to `data/seed/`.
- Record every download's URL and access date in `data/seed/sources.md`.
- Resample every layer to one 30 m grid before building features.
- Split train and test by space, using the region column. Never shuffle pixels across the box.
- Publish the AUC you measure in `artifacts/metrics.json`. 0.85 is not a gate.
- Tiles are XYZ PNG in EPSG:3857 so they sit on Mapbox terrain.
- Model B weights are named constants with a comment on each.

## Environment

The ML requirements file lands with step 10. From then on:

```bash
python3.11 -m venv ml/.venv && source ml/.venv/bin/activate
pip install -r ml/requirements.txt
```
