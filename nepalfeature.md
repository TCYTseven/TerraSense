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