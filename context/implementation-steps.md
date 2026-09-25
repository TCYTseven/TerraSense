# Implementation steps

Twenty-five steps from an empty checkout to the HackGT demo in [TerraSense.md](TerraSense.md).

Finish each step on a track before you start the next one on that track. After step 6, the globe work (steps 7–9) and the data work (steps 10–14) can run at the same time.

The frontend app already exists in `frontend/`. Treat step 1 as done for that folder, then keep going.

Stay inside the hackathon scope. One live mountain (Mount Rainier), landslide risk only, five agents, one Discord alert, one hiker card.

## Checklist

- [x] 1. Lay out the repo and environment
- [x] 2. Apply the dark dispatch theme
- [x] 3. Stand up the FastAPI service
- [x] 4. Create the Postgres schema
- [x] 5. Seed mountains and empty Rainier trails
- [x] 6. Ship the mountain read API
- [x] 7. Add the typed frontend API client
- [x] 8. Render the 3D globe and risk markers
- [x] 9. Search, fly to a mountain, and open its page
- [ ] 10. Download the Rainier source layers (DEM and land cover done. Landslide points pending, see `data/seed/sources.md`)
- [ ] 11. Build the terrain feature table (feature stack done. Labeled table waits on the step 10 landslide points)
- [ ] 12. Train the susceptibility model (LightGBM path ready. The map uses a knowledge-driven index until labels exist)
- [x] 13. Render susceptibility map tiles
- [ ] 14. Import trails and historical landslide pins (67 OpenStreetMap trails and the hero trail's 55 mile segments done. The API returns `historical_events`, empty until the step 10 landslide points exist)
- [x] 15. Open the Mapbox mountain view (built on MapLibre GL with AWS Terrain Tiles, so no token is needed. A Mapbox token switches the relief to satellite)
- [x] 16. Toggle susceptibility and historical pins (the Past landslides toggle stays disabled until the step 10 landslide points exist)
- [ ] 17. Score 72-hour probability from live rain
- [x] 18. Draw the heat map, hazard polygon, and trail risk (until step 17's Model B lands, the heat map is the susceptibility map, labeled as a stand-in; `backend/app/ml/probability.py` switches to Model B when the module exists)
- [x] 19. Add one bypass around the worst segment (routed on the OpenStreetMap network per run; where no trail runs around the flagged miles, the answer is to turn back)
- [x] 20. Define agent schemas, tools, and prompts (plus the Gemini Flash and Grok providers and the router that picks between them)
- [x] 21. Run the five-agent pipeline (checked against a fake of both APIs; no live Gemini or xAI call has run yet)
- [x] 22. Expose analyze, run status, and the live stream
- [x] 23. Show the agent stream and the hazard panel (plus the reasoning side panel)
- [ ] 24. Post the ranger alert to Discord
- [ ] 25. Show the hiker card and rehearse the demo

## Shared facts

Use these values everywhere so the globe, the model, and the map describe the same place.

| Item | Value |
|---|---|
| Live mountain | Mount Rainier. Slug `mount-rainier`. `is_live = true` |
| Peak | 46.8523, -121.7603. Elevation 4392 m |
| Bounding box | West -121.93, south 46.76, east -121.54, north 46.96 |
| Static markers | Two other peaks. Name, lat, lon, and a fixed risk level only |
| Risk levels | `low`, `moderate`, `high`, `extreme` |
| Probability bins | Low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7 |
| Tiles | XYZ, EPSG:3857, so they sit on the map's 3D terrain |

Rainier bounding box as numbers: `[-121.93, 46.76, -121.54, 46.96]`.

## Repo shape

```
frontend/                 Next.js app (already created)
backend/app/              FastAPI app
ml/scripts/               Offline DEM, training, and tiling scripts
ml/artifacts/             Model file, metrics, susceptibility raster
data/raw/                 Downloads. Gitignore this
data/processed/           Derived rasters. Gitignore this
data/seed/                Small JSON and GeoJSON committed to git
```

---

## 1. Lay out the repo and environment

**Outcome.** Anyone can clone the repo, copy the env file, and see which process owns which folder.

**Build.**

- Add `backend/`, `ml/scripts/`, `ml/artifacts/`, and `data/seed/`.
- Gitignore `data/raw/`, `data/processed/`, `.env`, `ml/artifacts/*.tif`, and Python virtualenvs.
- Add a root `.env.example` with `DATABASE_URL`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAPBOX_TOKEN`, the LLM key and models (since step 20: `GEMINI_API_KEY`, `GEMINI_MODEL`, `XAI_API_KEY`, `GROK_MODEL`), and `DISCORD_WEBHOOK_URL`.
- Add a root README with three commands: frontend dev server, API dev server, and "where the spec lives."

**Done when.** A new shell can read `.env.example` and name the folder for the UI, the API, and the offline model.

## 2. Apply the dark dispatch theme

**Outcome.** Every later screen inherits the same colors and type.

**Build.**

- In `frontend/app/globals.css`, set the background to `#0A0E14`, panels to `#151B23`, text to `#E6EDF3`, muted text to `#8B949E`, and the accent to `#22D3EE`.
- Reserve green `#22C55E`, amber `#F59E0B`, orange `#F97316`, and red `#EF4444` for risk. Use them nowhere else.
- Load a geometric sans for UI text and a monospace face for scores, miles, and timestamps.
- Make the root layout full viewport height with no default Next.js boilerplate on the home page.

**Done when.** The home page is a full-bleed dark screen with the TerraSense name in the top left and no light-theme chrome.

## 3. Stand up the FastAPI service

**Outcome.** The browser can call a local API.

**Build.**

- Create a Python 3.11+ virtualenv and a `backend/requirements.txt` with FastAPI, Uvicorn, Pydantic, HTTPX, and the Postgres driver you will use in step 4.
- `backend/app/main.py` serves `GET /health` and allows `http://localhost:3000` in CORS.
- Run it on port 8000.

**Done when.** `curl localhost:8000/health` returns a JSON ok payload, and the browser console shows no CORS error from the Next.js origin.

## 4. Create the Postgres schema

**Outcome.** The tables from the spec exist, with GeoJSON stored as JSON.

**Build.**

- Provision Postgres on Neon or Supabase. Save `DATABASE_URL`.
- Create `mountains`, `trails`, `trail_segments`, `analysis_runs`, `hazards`, and `alerts` with the columns in the spec.
- Store line and polygon geometry in `jsonb`. Skip PostGIS.
- Put the SQL in `backend/app/schema.sql` and apply it with one command.

**Done when.** All six tables exist and a fresh database can be recreated from `schema.sql`.

## 5. Seed mountains and empty Rainier trails

**Outcome.** The globe and the mountain page have rows to read before the model exists.

**Build.**

- Commit `data/seed/mountains.json` with Mount Rainier (`is_live: true`, risk `moderate` as a placeholder) and two static mountains (`is_live: false`, a fixed risk).
- Commit a tiny `data/seed/trails.geojson` for one named Rainier trail, even if the line is rough. Replace it in step 14.
- Write `backend/app/seed.py` to load both files.

**Done when.** The `mountains` table has three rows and Rainier has at least one trail row.

## 6. Ship the mountain read API

**Outcome.** The frontend can list mountains and open one mountain with its trails.

**Build.**

- `GET /mountains` returns id, name, slug, lat, lon, elevation, region, `current_risk_level`, `last_analyzed_at`, and `is_live`.
- `GET /mountains/{slug}` returns that mountain, its trails, and its active hazard when one exists.
- Static mountains return their seed risk. They do not grow an analyze action.

**Done when.** `GET /mountains` returns three mountains and `GET /mountains/mount-rainier` returns the seeded trail.

## 7. Add the typed frontend API client

**Outcome.** UI code calls one module and shares types with the stream you will add later.

**Build.**

- Add `frontend/lib/types.ts` for `Mountain`, `Trail`, `TrailSegment`, `Hazard`, `RiskLevel`, and `AgentEvent`.
- `AgentEvent` is `{ run_id, agent, status, summary, payload }`. `agent` is `terrain | weather | trail | synthesizer | writer`. `status` is `waiting | running | done | error`.
- Add `frontend/lib/api.ts` with `getMountains`, `getMountain`, and a base URL from `NEXT_PUBLIC_API_URL`.
- Add `frontend/lib/fixtures/run.json` with one finished five-agent run so the panel can be built before the LLM is wired.

**Done when.** The home page logs three mountains from the API, and the fixture file type-checks as `AgentEvent[]`.

## 8. Render the 3D globe and risk markers

**Outcome.** The first screen is the demo hook.

**Build.**

- Install `three`, `@react-three/fiber`, and `react-globe.gl` (or `three-globe`).
- Render a dark satellite globe, full viewport, with a light atmosphere and a slow idle spin.
- Place three markers from `GET /mountains`. Color each marker from its risk level.
- Hover shows name, risk, and last refresh time.
- Keep textures modest. Three markers is the whole set.

**Done when.** The globe spins, drag and zoom work, and the three markers show the risk colors from the database.

## 9. Search, fly to a mountain, and open its page

**Outcome.** A click or a search moves the camera, then opens the mountain.

**Build.**

- Center a search box. It matches mountain names. "Mount Rainier" flies there.
- On marker click or search, animate the camera to that lat/lon in about 1.5 seconds, then route to `/mountains/[slug]`.
- The mountain route renders the name, elevation, region, and risk from the API. The map comes in step 15.
- Static mountains open the same page and show their fixed risk. Hide **Analyze now** unless `is_live` is true.

**Done when.** Search and click both land on `/mountains/mount-rainier` after a single camera move, with no jump cut.

## 10. Download the Rainier source layers

**Outcome.** Offline scripts have a DEM, a land-cover raster, and landslide points for the bounding box.

**Build.**

- Download one elevation raster clipped to the shared bounding box. Use Copernicus DEM 30 m or USGS 3DEP. Save it under `data/raw/`.
- Download one land-cover raster for the same box. Use NLCD or ESA WorldCover.
- Download landslide points that fall inside the box from the NASA Global Landslide Catalog or a USGS inventory. Save a small GeoJSON copy into `data/seed/landslides.geojson` for the map pins.
- Record the source URL and access date in `data/seed/sources.md`.

**Done when.** The DEM, land cover, and point file all cover the shared bounding box, and `sources.md` names each file.

## 11. Build the terrain feature table

**Outcome.** Model A has one row per pixel and a stable label.

**Build.**

- In `ml/scripts/build_features.py`, derive slope, aspect, curvature, elevation, distance to drainage, land cover, and a topographic wetness index. Use rasterio. Use richdem only if wetness is awkward in rasterio.
- Resample every layer to the same 30 m grid.
- Buffer landslide points by about 50 m for positives. Sample negatives from the rest of the box at about one positive to three negatives.
- Write `data/processed/features.parquet` (or CSV) with those columns plus `label` and a region id you can split on.

**Done when.** The table has the seven features, a 0/1 label, and a region column, and the row count is printed by the script.

## 12. Train the susceptibility model

**Outcome.** A LightGBM model and a susceptibility raster exist, with an honest score.

**Build.**

- `ml/scripts/train_susceptibility.py` trains a LightGBM binary classifier.
- Hold out a spatial block, using the region column. Do not shuffle pixels across the box.
- Save the model, a susceptibility GeoTIFF aligned to the feature grid, feature-importance values, and `ml/artifacts/metrics.json` with AUC and precision at the high threshold.
- Write the AUC you get into `metrics.json`. Leave the demo copy for step 25.

**Done when.** The script prints AUC and writes a susceptibility raster that covers the Rainier box.

## 13. Render susceptibility map tiles

**Outcome.** Mapbox can drape the static layer on 3D terrain.

**Build.**

- `ml/scripts/render_tiles.py` colorizes susceptibility with the risk ramp (low toward blue-green, high toward red) and writes XYZ PNG tiles in EPSG:3857.
- Put tiles where the API can serve them, for example `backend/tiles/susceptibility/{z}/{x}/{y}.png`.
- Add `GET /mountains/{slug}/layers/susceptibility` and return a tile URL template. Rainier is the only slug with tiles.

**Done when.** Opening one tile URL in a browser shows a transparent PNG, and the URL template uses `{z}/{x}/{y}`.

## 14. Import trails and historical landslide pins

**Outcome.** The map has real lines and real past events.

**Build.**

- Pull foot paths in the bounding box from OpenStreetMap (Overpass or a Washington extract). Save `data/seed/trails.geojson`.
- Pick one hero trail that crosses a steep drainage, plus a second line you can use as the bypass in step 19.
- Split the hero trail into ordered segments with `start_mile` and `end_mile`. Load segments into `trail_segments`.
- Load `data/seed/landslides.geojson` into a `historical_events` JSON file the API can return. A table is optional. An endpoint is required: include the points on `GET /mountains/mount-rainier`.

**Done when.** Rainier returns a trail with several mile-marked segments and a list of historical points inside the box.

## 15. Open the Mapbox mountain view

**Outcome.** `/mountains/mount-rainier` is a terrain map plus a side panel.

**Build.**

- Add Mapbox GL JS. Read the token from `NEXT_PUBLIC_MAPBOX_TOKEN`.
- Fill about 70% of the width with a satellite map, 3D terrain, and exaggeration around 1.5. Center it on the mountain.
- Draw the seeded trail as a line.
- The right panel shows name, elevation, region, overall risk, one placeholder sentence, and the trail list.

**Done when.** The Rainier page shows 3D terrain and the trail line, and the panel matches the API record.

## 16. Toggle susceptibility and historical pins

**Outcome.** A judge can turn the static science layers on and off.

**Build.**

- Add a small toggle group over the lower left of the map.
- The susceptibility toggle adds the XYZ raster source from step 13. Fade it in over about 400 ms.
- Historical pins use the landslide points from step 14. Clicking a pin shows date, type, and source.
- Check that the raster sits on the terrain and not offset from the ridges. Fix the tile scheme before you go on.

**Done when.** Both toggles work, pins open a small popup, and the susceptibility image lines up with the ridges.

## 17. Score 72-hour probability from live rain

**Outcome.** Model B turns cached susceptibility and today's rain into a probability raster.

**Build.**

- Call Open-Meteo for the Rainier peak. Read precipitation for the past 7 days and the next 3 days. No API key.
- Implement `P = sigmoid(w1 * susceptibility + w2 * rainfall_exceedance + w3 * moisture_index)` in `backend/app/ml/model_b.py`.
- Keep `w1`, `w2`, and `w3` as named constants. Document them next to the function.
- Map probability through the shared bins.
- Cache the Open-Meteo response for a few minutes so a demo retry does not wait on the network twice.

**Done when.** A Python call prints a probability raster summary and the rain totals that produced it, in well under 30 seconds after the first fetch.

## 18. Draw the heat map, hazard polygon, and trail risk

**Outcome.** The mountain shows where the model says the hazard is, and which trail miles cross it.

**Build.**

- Render the probability raster to XYZ tiles the same way as susceptibility. This is the default layer.
- Extract the worst contiguous high cluster into one GeoJSON polygon. Store it as a hazard row linked to a run, or as a preview hazard before agents exist.
- Intersect that polygon with trail segments. Set each segment's `risk_level` and `probability`.
- Color the trail line by segment risk.
- `GET /mountains/mount-rainier/layers/probability` returns the tile template.

**Done when.** The default map shows the heat map and a trail that changes color along its length, and one polygon exists for the worst cluster.

## 19. Add one bypass around the worst segment

**Outcome.** The product can name a way around the flagged miles.

**Build.**

- Prefer a short path on the trail graph that avoids segments at `high` or `extreme`.
- If the graph is not ready, use the second line from step 14 as a hand-authored bypass and store its added distance and added elevation as constants you can defend.
- Save the bypass GeoJSON on the trail or the run.
- The Trail Analyst in step 21 explains this geometry. It does not invent a new line.

**Done when.** The API returns a bypass name, added kilometers, added elevation, and a line that does not overlap the worst segment.

## 20. Define agent schemas, tools, and prompts

**Outcome.** Each agent has a fixed input, a Pydantic output, and a prompt that asks for that JSON only.

**Build.**

- Add schemas for Terrain, Weather, Trail, Synthesizer, and Alert Writer.
- Terrain output matches the spec: one `hazard_zone` with type, severity, probability, drivers, confidence, and notes.
- Tools return precomputed facts only: `get_raster_summary`, `get_trail_segments`, `get_weather`, `get_historical_events`.
- `get_raster_summary` returns the cluster from step 18. The model does not scan pixels.
- The trail tool returns the bypass from step 19.
- A router picks the model for every call (user direction, Sep 25, 2026): Gemini Flash or Grok. Terrain, Weather, and Trail start on Gemini Flash; Synthesizer and Alert Writer start on Grok. A borderline or high-stakes fast task moves up to Grok, a clear low-stakes strong task moves down to Gemini, a run past 70% of its minute moves to Gemini, and the other provider is the fallback. Each decision and its rules go into the agent's trace for the reasoning panel.

**Done when.** Each schema rejects a missing field, and each tool returns data for `mount-rainier` with no LLM call.

## 21. Run the five-agent pipeline

**Outcome.** One function produces both texts and a consensus severity.

**Build.**

- Run Terrain and Weather together. Then Trail. Then Synthesizer. Then Alert Writer.
- Synthesizer confidence is the weighted average from the spec. Weights are constants.
- If two severity labels differ by two or more levels, set `needs_review` and make the ranger text an advisory.
- Alert Writer returns a short ranger body and a short hiker sentence. Ranger copy names the trail and miles. Hiker copy names the bypass.
- Cap each call. The whole pipeline should finish in about a minute.

**Done when.** A local function call prints five JSON objects, a final severity, and both paragraphs, using the Rainier tools.

## 22. Expose analyze, run status, and the live stream

**Outcome.** The browser can start a run and watch agents finish.

**Build.**

- `POST /mountains/{slug}/analyze` returns `{ run_id }` and starts the pipeline in the background. Reject the call when `is_live` is false.
- Store run state in the API process, keyed by `run_id`. Persist `analysis_runs` and the hazard row when the run finishes.
- `GET /runs/{run_id}` returns status plus agent outputs.
- `WS /runs/{run_id}/stream` emits an `AgentEvent` when an agent starts and when it finishes.
- On failure, emit `status: error` and store the failed run. Do not hang the socket.

**Done when.** A client that connects to the socket sees terrain and weather start together, then the later agents, then a completed `GET /runs/{run_id}`.

## 23. Show the agent stream and the hazard panel

**Outcome.** **Analyze now** drives the side panel, and the hazard pin tells a judge what to do.

**Build.**

- Show five rows: Terrain, Weather, Trail, Synthesizer, Alert Writer. Each row has waiting, running, and done. The running row pulses.
- **Analyze now** calls `POST /analyze`, opens the socket, and fills the rows.
- When the run completes, place the hazard pin on the polygon. The panel always shows, in order: what it is, why it was flagged, confidence, and how to avoid it.
- Show rain text in the panel: past 72 hours and the next 24 hours. This is text, not a map layer.
- Disable the button while a run is in progress. If the socket errors, say that the run failed and leave the last successful hazard on the map.

**Done when.** One click on Rainier streams all five rows and opens a pin whose four fields match the saved hazard.

## 24. Post the ranger alert to Discord

**Outcome.** A finished run lands in a Discord channel with a link back to the pin.

**Build.**

- After Alert Writer succeeds, `POST` the webhook in `DISCORD_WEBHOOK_URL`.
- The message includes hazard type, severity, trail name, mile range, confidence, recommended action (`monitor` or `close`), the ranger paragraph, and a link to `/mountains/mount-rainier?hazard={id}`.
- That query opens the mountain page with the pin selected and the heat map on.
- Store the alert row. If Discord returns an error, keep the in-app alert text and show a send failure. The map still works.
- Send a real message twice before you call this step done.

**Done when.** A full analyze posts one Discord message, and the link opens the hazard pin.

## 25. Show the hiker card and rehearse the demo

**Outcome.** The second audience is on screen, and the two-minute demo can be repeated.

**Build.**

- `GET /forecast?mountain_id=&trail_id=` returns the level, the hiker sentence, the bypass name, added distance, and added elevation from the latest successful run.
- **Hiker forecast** opens a larger-type card on the same dark background and draws the bypass on the map.
- Add empty, loading, and error states for the globe, the mountain, and the run.
- Write the real AUC, the real weights, and the real data sources into the Devpost draft in `TerraSense.md`.
- Rehearse the script in that file three times: globe, fly-in, heat map, pin, analyze, Discord, hiker card.
- Keep one finished run visible as a fallback if the live call fails on stage.

**Done when.** A person who has not seen the app can follow the demo script and reach the Discord message and a hiker card that names the bypass.

## If you are behind

Drop work in this order. The demo still holds.

1. The two static globe markers (step 5's extra mountains, and their markers in step 8).
2. The susceptibility toggle (step 16). Keep the 72-hour heat map.
3. A computed bypass (step 19). Keep a named bypass in the hiker sentence.
4. The Synthesizer as its own model call (step 21). Let Alert Writer merge the three reports.

Keep the globe, the heat map, the agent stream, and the Discord message.
