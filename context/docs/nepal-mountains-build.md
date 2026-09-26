# Nepal mountains — build steps and Claude prompt

Goal: put **Nepal peaks on the globe for a current-event demo**, and make **Mount Everest** open like Rainier (terrain, heat, trails, **Analyze now**) using the pack pipeline that already exists. No new database product, no river model, no second LightGBM.

The earlier file `nepal-current-event-plan.md` stopped at spoken copy. **This file replaces that as the build.** Copy is still required, and it stays honest: Everest’s heat is a **knowledge-driven index**, not the Cascades-trained model.

---

## Paste this prompt into Claude

```text
You are implementing the Nepal current-event mountains in the TerraSense repo at the workspace root. Read context/docs/nepal-mountains-build.md and follow it. Also read AGENTS.md, data/AGENTS.md, backend/AGENTS.md, and ml/AGENTS.md before you edit.

Do this now. Do not stop at a demo script.

Scope
- Featured Nepal catalog peaks in data/seed/mountains_test.json (the file SEED_MODE=mountainstest loads): mount-everest, annapurna-i, manaslu, kangchenjunga. Keep their existing slugs, lat, lon, and elevation. Set region strings so the hover card says they are in Nepal (Everest may stay "Mahalangur Himal, Nepal / China"). Set current_risk_level to high. Leave is_live false in JSON. python -m app.seed sets is_live from a servable raster, not from the JSON flag.
- Rainier-like render for mount-everest only. It is already in ml/scripts/mountain_packs.py PACKS and data/seed/packs/index.json, hero "Everest Base Camp Trek", bbox around 27.988, 86.925. Do not add Annapurna, Manaslu, or Kangchenjunga as packs in this pass. They stay catalog peaks with satellite hover and the synthetic heat drape.
- Do not train LightGBM on Nepal. Packs use the knowledge-driven index. Do not copy Rainier's susceptibility.tif onto Everest.
- Do not add a river layer, gauge API, or flood polygon. One sentence in the demo script is enough: debris from slope failure reaches valleys. The spoken script in context/TerraSense.md already says the heat is illustrative. Update that sentence so Everest's pack heat is called a knowledge-driven index, not a Cascades forecast.
- Do not put Nepal points into data/seed/landslides.geojson. History for a pack reads data/seed/packs/<slug>/landslides.geojson. An empty collection is fine.

Build
1. From the repo root, if ml/artifacts/packs/mount-everest/ does not contain the susceptibility raster the pack scripts write, run:
   python ml/scripts/build_pack.py mount-everest
   This downloads DEM and WorldCover, builds the 30 m stack, writes the index raster, renders XYZ tiles under backend/tiles/mount-everest/, and refreshes data/seed/packs/mount-everest/ trails. Skip stages whose outputs already exist. Rasters and tiles are gitignored. They must exist on the machine that runs the API. Seeding Postgres does not upload them.
2. If you change PACKS, run: python ml/scripts/mountain_packs.py --write-index
   Everest is already in the index. Do not rewrite the index unless the registry changed.

Database, both targets
Root .env has DB, DATABASE_URL_LOCAL, and DATABASE_URL_PROD. backend/app/config.py picks the URL from DB=LOCAL or DB=PROD. Never print the URLs.

From backend/, with the venv:
  DB=LOCAL python -m app.schema
  DB=LOCAL python -m app.seed
  DB=PROD python -m app.schema
  DB=PROD python -m app.seed

schema is IF NOT EXISTS and must create mountain_satellite_images. seed upserts mountains from the active SEED_MODE file, trails, satellite_images.json, and runs mark_packs_live, which sets is_live true only when the susceptibility raster exists on this disk. After PROD seed, Everest is live in Tiger only if this same machine has the raster. Say that in the summary.

Check
- curl the local API GET /mountains/mount-everest and confirm is_live true after the raster exists, trails non-empty, satellite_image_url set.
- GET /mountains/mount-everest/layers/susceptibility returns a tile template, not the synthetic /tiles/synthetic/ path.
- annapurna-i, manaslu, and kangchenjunga stay is_live false.
- Do not claim a river forecast or a Himalaya-trained AUC.

Commit only if the user asked. Do not commit .env or rasters.
```

---

## Why this shape

| Peak | What the user sees | How |
|---|---|---|
| Mount Rainier | Trained heat, mile segments, agents, simulate | Existing live mountain. Do not retarget it. |
| Mount Everest | Same page shape: real tiles, EBC trails, **Analyze now** | `python ml/scripts/build_pack.py mount-everest`, then seed. Heat is an **index**, labeled as one. |
| Annapurna I, Manaslu, Kangchenjunga | Globe search, satellite hover, synthetic drape | Rows in `mountains_test.json` + `satellite_images.json`. No pack. |

`python -m app.seed` calls `mark_packs_live`. A pack becomes `is_live` when `data/seed/packs/index.json` lists it **and** `ml/artifacts/packs/<slug>/` has the susceptibility raster. Missing raster stays a static marker. The API must be restarted on the machine that holds the raster.

Tiger (`DB=PROD`) and local Postgres (`DB=LOCAL`) both need schema + seed. The raster is not in the database.

---

## Steps

### 1. Catalog rows

Edit `data/seed/mountains_test.json` only. `SEED_MODE=mountainstest` in `.env.example` is the default.

For `mount-everest`, `annapurna-i`, `manaslu`, and `kangchenjunga`:

- Keep `slug`, `lat`, `lon`, `elevation_m`.
- `current_risk_level`: `high`.
- `is_live`: `false` in the file.
- `region`: include `Nepal` so the hover card reads as the current-event set. Everest can stay `Mahalangur Himal, Nepal / China`.

Do not delete other peaks.

### 2. Render Everest like a pack, not like Rainier's model

From the repo root, ML venv active:

```bash
python ml/scripts/build_pack.py mount-everest
```

That script already runs, in order: `download_sources.py`, `build_features.py`, the knowledge-driven index (not `train_regional_susceptibility.py`), `render_tiles.py`, `import_trails.py`, `build_trail_network.py`.

Outputs that matter:

- `ml/artifacts/packs/mount-everest/` — index raster (gitignored).
- `backend/tiles/mount-everest/susceptibility/` — XYZ PNGs (gitignored).
- `data/seed/packs/mount-everest/` — trails, segments, network, landslides. These are committed.

Everest is already registered:

- `ml/scripts/mountain_packs.py` — `slug="mount-everest"`, hero `Everest Base Camp Trek`, 18 km bbox.
- `data/seed/packs/index.json` — same peak and bbox.

Run `python ml/scripts/mountain_packs.py --write-index` only if `PACKS` changed.

### 3. Seed local and Tiger

From `backend/`, backend venv, repo-root `.env` loaded by the app:

```bash
DB=LOCAL python -m app.schema
DB=LOCAL python -m app.seed
DB=PROD python -m app.schema
DB=PROD python -m app.seed
```

`app.seed` upserts the active catalog, pack trails, `data/seed/satellite_images.json` into `mountain_satellite_images`, then `UPDATE mountains SET is_live = true` for servable slugs. Rainier stays live. Everest joins it when the raster is on disk.

If `DB=PROD` fails, fix `DATABASE_URL_PROD` in `.env`. Do not print the URL.

### 4. Prove the API

API on port 8000, same machine as the raster:

```bash
curl -s localhost:8000/mountains/mount-everest | head -c 400
curl -s localhost:8000/mountains/mount-everest/layers/susceptibility
```

Pass: `is_live` true, trails present, layer `tiles` path contains `/tiles/` and the Everest slug, not `/tiles/synthetic/`.

```bash
curl -s localhost:8000/mountains/annapurna-i
curl -s localhost:8000/mountains/manaslu
curl -s localhost:8000/mountains/kangchenjunga
```

Pass: those three stay `is_live` false. Their susceptibility layer may be the synthetic template. That is expected.

Restart `uvicorn` after seed. Search **Everest** on the globe. The pin is live, so it is kept even when the globe caps markers at 50.

### 5. Words

In `context/TerraSense.md`, the Nepal beat must say:

- Everest heat is a **knowledge-driven index** for this box, not the Cascades LightGBM and not a live Nepal forecast.
- Annapurna, Manaslu, and Kangchenjunga are catalog markers for the same news cycle.
- Rivers: debris from failed slopes reaches valleys. No river stage.

Do not add UI that says the index is Model B.

---

## Out of scope for this pass

- Training or fine-tuning on Himalayan landslide labels.
- Packs for Annapurna, Manaslu, or Kangchenjunga.
- A river geometry layer.
- Marking Everest `is_live` in JSON by hand. Seed owns that flag.
- Copying `ml/artifacts/susceptibility.tif` into the Everest folder.

---

## If the pack build fails

| Failure | What to do |
|---|---|
| DEM or WorldCover download | Rerun `python ml/scripts/build_pack.py mount-everest`. Completed stages skip. |
| No named trails | Page still opens. Hero can be empty. Do not invent a line. |
| Raster missing after seed | Everest stays static and the map uses the synthetic drape. The build did not finish. Do not flip `is_live` in SQL. |
| Tiger seed works, heat is still synthetic | The API process is not on the disk that has `ml/artifacts/packs/mount-everest/`. |
