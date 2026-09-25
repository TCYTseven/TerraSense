# ML agent guide

Offline Python for TerraSense: source downloads, the terrain feature table, the LightGBM susceptibility model, and map tiles. Track: ML and data. Nothing here runs as a server.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## Steps this folder owns

| Step | Script | Writes |
|---|---|---|
| 10 | `scripts/download_sources.py` | DEM and land cover in `data/raw/`, `data/seed/landslides.geojson`. Record each download in `data/seed/sources.md` by hand |
| 11 | `scripts/build_features.py` | `data/processed/features.parquet` |
| 12 | `scripts/train_susceptibility.py` | Model, `artifacts/metrics.json`, feature importance, susceptibility GeoTIFF |
| 13, 18 | `scripts/render_tiles.py` | XYZ PNGs in `backend/tiles/`. The API renders the probability layer itself on each run (`backend/app/assessment.py`) |
| 14 | `scripts/import_trails.py` | `data/seed/trails.geojson`, `data/seed/trail_segments.geojson` (the hero trail's mile segments), and the walkable network cache in `data/raw/` |
| 17 | `backend/app/ml/model_b.py` | Live 72-hour probability from susceptibility plus Open-Meteo rain. `backend/app/ml/probability.py` calls `run(rain)` and reads `.probability`, `.transform`, and `.crs` from the result; until the module exists the heat map is the susceptibility stand-in |
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
- Publish the AUC you measure in `artifacts/metrics.json`. 0.85 is not a gate. Until landslide labels exist, `metrics.json` says `trained: false` and `auc: null`: never present the knowledge-driven index as a trained model.
- Tiles are XYZ PNG in EPSG:3857 so they sit on the map's 3D terrain.
- Model B weights are named constants with a comment on each.

## Environment

Run from the repo root:

```bash
python3.11 -m venv ml/.venv && source ml/.venv/bin/activate
pip install -r ml/requirements.txt
python ml/scripts/download_sources.py      # step 10: DEM, land cover, landslide points
python ml/scripts/build_features.py        # step 11: 30 m feature stack, labeled table when points exist
python ml/scripts/train_susceptibility.py  # step 12: LightGBM with labels, knowledge-driven index without
python ml/scripts/render_tiles.py          # step 13: backend/tiles/susceptibility/{z}/{x}/{y}.png
python ml/scripts/import_trails.py         # step 14: OpenStreetMap trails via Overture, the hero trail's segments
python ml/scripts/build_trail_network.py  # step 19: the network the bypass routes on (needs step 14's cache and the DEM)
```

Each download is recorded in `data/seed/sources.md`. The landslide stage needs a network that reaches data.nasa.gov, or a hand-downloaded CSV passed with `--glc-csv`.
