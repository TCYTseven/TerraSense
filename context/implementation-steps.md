# Implementation steps

Thirty-one steps from an empty checkout to the HackGT demo in [TerraSense.md](TerraSense.md). Steps 26 to 30 were added on Sep 25, 2026 for the mountain panel and simulation (spec 6.8), and step 31 the same night, to wire the rebuilt hill card to the backend.

This file has two parts:

- [Part 1: Pending](#part-1-pending) is the work that is left, with the full build notes for each step.
- [Part 2: Done](#part-2-done) records what each finished step shipped and how it was checked.

Status as of Saturday, Sep 26, 2026. The open list is [9-26-todo.md](9-26-todo.md). Step numbers never change, because commits and branches name them (`Step N: <title>`, `step-<N>-<short-name>`).

Finish each step on a track before you start the next one on that track. Stay inside the hackathon scope: one live mountain (Mount Rainier), landslide risk only, seven agents (five analysts, a Risk Synthesizer, an Alert Writer), the hill detail card, one hiker card, one mountain panel with a runout simulation. The ranger alert stays in the app: Discord was dropped on Sep 25, 2026.

## Checklist

### Pending

- [x] 10. Download the Rainier source layers (DEM, land cover, 4 NASA events, and 33 documented supplemental inventory labels are present)
- [x] 11. Build the terrain feature table (30 m seven-band stack and 1,224-row labeled table are present)
- [x] 12. Train the susceptibility model (LightGBM trained; held-out spatial AUC 0.715; susceptibility tiles rendered)
- [x] 14. Import trails and historical landslide pins (67 OpenStreetMap trails, 55 hero segments, and 37 Rainier historical pins are present)
- [x] 17. Score 72-hour probability from live rain (Model B combines susceptibility with forecast rain and antecedent moisture)
- [ ] 26. Rank the pressure points
- [ ] 27. Trace a runout from a pressure point
- [ ] 28. Expose simulate, the stream, and the callouts
- [ ] 29. Open the mountain panel over the globe
- [ ] 30. Play the simulation in the panel
- [ ] 31. Wire the hill card to the run stream and the advisory (agents and Reactive Measures stream from the API. Trail scores, the overall score, and preventative measures are still illustrative)
- [ ] 32. Build mountain data packs for the demo peaks (Rainier-style DEM, land cover, index, tiles, and trails for 7 more peaks, 1-2 per continent)
- [ ] Before the demo: provision hosted Postgres, run one live pipeline with real Gemini and xAI keys, and rehearse (follow-up to steps 4 and 25)

### Done

- [x] 1. Lay out the repo and environment
- [x] 2. Apply the dark dispatch theme
- [x] 3. Stand up the FastAPI service
- [x] 4. Create the Postgres schema
- [x] 5. Seed mountains and empty Rainier trails
- [x] 6. Ship the mountain read API
- [x] 7. Add the typed frontend API client
- [x] 8. Render the 3D globe and risk markers
- [x] 9. Search, fly to a mountain, and open its page
- [x] 13. Render susceptibility map tiles
- [x] 15. Open the Mapbox mountain view (built on MapLibre GL with AWS Terrain Tiles, so no token is needed. A Mapbox token switches the relief to satellite)
- [x] 16. Toggle susceptibility and historical pins (the Past landslides toggle stays disabled until the step 10 landslide points exist)
- [x] 18. Draw the heat map, hazard polygon, and trail risk (until step 17's Model B lands, the heat map is the susceptibility map, labeled as a stand-in; `backend/app/ml/probability.py` switches to Model B when the module exists)
- [x] 19. Add one bypass around the worst segment (routed on the OpenStreetMap network per run; where no trail runs around the flagged miles, the answer is to turn back)
- [x] 20. Define agent schemas, tools, and prompts (plus the Gemini Flash and Grok providers and the router that picks between them)
- [x] 21. Run the five-agent pipeline (checked against a fake of both APIs; no live Gemini or xAI call has run yet. Since grown to seven agents: five analysts in parallel, then the Risk Synthesizer and the Alert Writer)
- [x] 22. Expose analyze, run status, and the live stream
- [x] 23. Show the agent stream and the hazard panel (plus the reasoning side panel. Replaced on the page by the hill detail card; see [Since the numbered steps](#since-the-numbered-steps))
- [x] 24. ~~Post the ranger alert to Discord~~ (dropped by the team on Sep 25, 2026. The ranger reads the alert in the app)
- [x] 25. Show the hiker card and rehearse the demo (walked in Chromium against the fake LLM APIs. Rehearse once more with real Gemini and xAI keys. The card is not rendered on the rebuilt page for now)

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
frontend/                 Next.js app
backend/app/              FastAPI app, assessment, agents, runs
backend/tests/            pytest suite and the fake LLM server
backend/tiles/            Rendered XYZ tiles. Gitignored
ml/scripts/               Offline DEM, training, tiling, and trail scripts
ml/artifacts/             Model file, metrics, susceptibility raster
data/raw/                 Downloads. Gitignored
data/processed/           Derived rasters. Gitignored
data/seed/                Small JSON and GeoJSON committed to git
```

## If you are behind

Drop work in this order. The demo still holds.

1. The callouts (step 28's model call; keep template callouts), then the simulation (steps 27, 28, 30). Keep step 29's panel, or let the click fly straight in as it does today.
2. The two static globe markers (step 5's extra mountains, and their markers in step 8).
3. The susceptibility toggle (step 16). Keep the 72-hour heat map.
4. A computed bypass (step 19). Keep a named bypass in the hiker sentence.
5. The Synthesizer as its own model call (step 21). Let the Alert Writer merge the five reports.
6. Step 31's live wiring. The hill card still demos on its illustrative data, labeled as such.

Keep the globe, the heat map, and the agent stream.

---

# Part 1: Pending

On main, steps 10, 11, 12, 14, and 17 are still open: there is no `data/seed/landslides.geojson`, `metrics.json` says `trained: false`, and `backend/app/ml/model_b.py` is absent, so the heat map stays the susceptibility stand-in.

That work is already on `origin/step-10-local-nasa-export` (landslide points, a 1,224-row labeled table, LightGBM with held-out AUC 0.715, 37 historical pins, and Model B). Merge it. Do not rebuild it. Main is six commits ahead of the branch point, so the merge has to keep the catalog and the live hill-card stream.

## 10. Download the Rainier source layers

**Outcome.** Offline scripts have a DEM, a land-cover raster, and landslide points for the bounding box.

**Done so far.** `ml/scripts/download_sources.py` writes and verifies the Copernicus DEM GLO-30, ESA WorldCover 2021 clip, and landslide points. NASA GLC is preferred; sparse high-accuracy NASA exports are supplemented by the official Washington Geological Survey Landslide Compilation layer so spatial training does not rely on one event cluster.

**Source note.** The supplied NASA export contributed 4 Rainier events, but only one is `1km` accurate; the script added 33 official Washington inventory polygons as conservative `1km` representative points. NASA events retain their original `1km`/`5km` accuracy, and no point was placed by hand.

**Done when.** The DEM, land cover, and `data/seed/landslides.geojson` cover the shared bounding box, `sources.md` names each source, and the downloader plus source adapter tests pass.

## 11. Build the terrain feature table

**Outcome.** Model A has one row per pixel and a stable label.

**Done so far.** `ml/scripts/build_features.py` writes `data/processed/features.tif`: a 30 m grid in UTM 10N (1004 × 757 cells) with seven bands (elevation, slope, aspect, curvature, distance to drainage, land cover, TWI). The current run writes a 1,224-row labeled table from 34 usable `exact`/`1km` points: 306 positives and 918 spatially excluded negatives across 14 regions.

**Left.**

- It writes `data/processed/features.parquet`: positives within 50 m of `exact` or `1km` points, negatives at about 1:3 from ground more than 500 m away, `label`, and `region` (7.5 km blocks). The feature and label contract has adversarial unit coverage for region isolation, accuracy filtering, binary labels, and duplicate pixel prevention.

**Done when.** The table has the seven features, a 0/1 label, and a region column, the script prints the row count, and the feature/label contract tests pass.

## 12. Train the susceptibility model

**Outcome.** A LightGBM model and a susceptibility raster exist, with an honest score.

**Done so far.** `ml/scripts/train_susceptibility.py` trains LightGBM on the 1,224-row table, holds out whole spatial regions, reports AUC and precision at 0.45, refits on every labeled row, and writes a full-map prediction. The current run has AUC `0.7150`, precision at High `0.0000`, 1,041 train rows, 183 test rows, and 306 positives. The model file, metrics, feature importance, GeoTIFF, and 383 z10–z14 XYZ tiles are present.

**Left.**

- No remaining step-12 implementation work. The score is reported honestly on a held-out spatial block; it is not treated as a 0.85 gate.

**Done when.** The script prints AUC, writes a trained susceptibility raster covering the Rainier box, `metrics.json` says `trained: true`, the model artifact exists, and susceptibility tiles render.

## 14. Import trails and historical landslide pins

**Outcome.** The map has real lines and real past events.

**Done so far.** 67 OpenStreetMap trails (via Overture Maps) are in `data/seed/trails.geojson`. The hero trail, the Skyline loop, is cut into 55 segments of 0.1 mile in `data/seed/trail_segments.geojson`. `backend/app/history.py` serves 37 in-bounds `historical_events` on `GET /mountains/mount-rainier`, and static mountains remain empty. Historical-pin contract tests cover source, accuracy, bbox, and the static-mountain boundary.

**Left.**

- None. The source file is committed, the API re-reads it when its mtime changes, and the **Past landslides** toggle is enabled for Rainier.

**Done when.** Rainier returns a trail with mile-marked segments and 37 non-empty historical points inside the box, static mountains return no catalog points, and a pin opens its popup on the map.

## 17. Score 72-hour probability from live rain

**Outcome.** Model B turns cached susceptibility and today's rain into a probability raster.

**Done so far.** `backend/app/weather.py` fetches Open-Meteo rain for Paradise, with a 5-minute cache and an offline fixture. `backend/app/ml/probability.py` is the seam, and `backend/app/ml/model_b.py` now produces the live probability raster.

**Build.**

- Implemented `P = sigmoid(w1 * susceptibility + w2 * rainfall_exceedance + w3 * moisture_index)` in `backend/app/ml/model_b.py`. The centered inputs keep dry, low-susceptibility cells below the high-risk bin.
- Expose `run(rain)` returning an object with `.probability` (float32 0 to 1 on the susceptibility grid, NaN outside the data), `.transform`, and `.crs`. If the shape differs, adapt `_from_model_b()` in `probability.py` and nothing else.
- Keep `w1`, `w2`, and `w3` as named constants. Document them next to the function.
- Map probability through the shared bins.

**Done when.** A Python call prints a probability raster summary and the rain totals that produced it, in well under 30 seconds after the first fetch. A run's `method` reads `model b`, and the stand-in note leaves the panel. `python -m app.assessment` now supplies the fetched rain to Model B and prints those totals.

## 26. Rank the pressure points

**Track.** ML and data, with the route in `backend/`.

**Outcome.** The panel can list the slopes most likely to fail.

**Build.**

- In `backend/app/ml/pressure.py` (free of API imports, like `hazard.py`), find 8-connected clusters at Moderate or above on the current probability map. Rank them by peak probability times area, and drop clusters under 0.05 km² or within 500 m of a better one. Keep up to `MAX_PRESSURE_POINTS` (5).
- For each point, return id, rank, level, peak probability, centroid, a simplified polygon, facing, elevation, the terrain drivers from the feature stack, and the nearest trail below it within 0.5 mi with its mile range.
- `GET /mountains/{slug}/pressure-points` returns `PressurePoint[]` (empty for static mountains). Add the Pydantic model and its mirror in `frontend/lib/types.ts` in the same commit.

**Done when.** `GET /mountains/mount-rainier/pressure-points` returns up to five ranked points in under a second, and the first matches the worst cluster on the heat map.

## 27. Trace a runout from a pressure point

**Track.** ML and data.

**Outcome.** One function turns a pressure point into frames and steps, with no model call.

**Build.**

- `backend/app/ml/runout.py`: from the point's cells at High or above, spread downslope on the 30 m DEM with multiple-flow-direction routing (Holmgren, exponent 4). Stop where the travel angle from the release drops below `REACH_ANGLE_DEG` (11) or the path passes `MAX_RUNOUT_M` (6000).
- Arrival time is path distance over `FRONT_SPEED_MS` (5). Intensity is the flow share through a cell, 0 to 1. All four constants are named and documented.
- Frames: the footprint every `FRAME_S` of simulated time, at most 40, as GeoJSON polygons with a `level` property on the shared bins (below Moderate left out).
- Steps: release, channel entry (first cell within 100 m of a D8 channel), each trail crossing (trail, mile range, flow level there), and stop (distance, drop). Each has a time and a point.

**Done when.** A Python call on Rainier's first pressure point prints the frame count, the steps with their times, and the runout length in under 3 seconds, and the frames grow monotonically.

## 28. Expose simulate, the stream, and the callouts

**Track.** Backend and agents.

**Outcome.** The browser can start a simulation and receive frames, steps, and callouts.

**Build.**

- `POST /mountains/{slug}/simulate` with `{ pressure_point_id }` returns `{ simulation_id }`. 409 for a static mountain, 404 for an unknown point. State lives in the API process, keyed by id, like runs. Nothing is written to Postgres.
- `WS /simulations/{id}/stream` sends one message with the frames and steps, then each callout, then a final message. `GET /simulations/{id}` returns the same, finished or not.
- Callouts: one model call through the existing router, strong tier. It reads the steps and the pressure point and returns two to four `{ step_id, audience: rangers | public, text }`, at least one of each. The schema is closed, like the agents'.
- Code checks every trail, mile, and time in the text against the steps, and enforces the word limits in the design addendum's Copy. On a failed check it runs one repair round, then the fallback provider, then templates. The trace records which.
- Add the models and their mirrors in `frontend/lib/types.ts` in the same commit. Test against `backend/tests/fake_llm.py`.

**Done when.** A socket client gets the frames and steps within 3 seconds of `POST`, then the callouts, then the final message, and a run with both providers down still ends with template callouts.

## 29. Open the mountain panel over the globe

**Track.** Frontend.

**Outcome.** A globe click opens the centered panel instead of routing to the mountain page.

**Build.**

- A marker click or search pick turns the globe to face the mountain (the first leg of the fly-to), pauses the spin, lays the scrim, and opens the panel. `?m=<slug>` reopens it on reload.
- Left: a compact MapLibre map from the same style module, with the heat map, trails, and numbered pressure point pins. Right: header, overall risk, the pressure point list, **Simulate**, and **Open ranger view**. Follow the design addendum's Mountain panel.
- **Open ranger view** closes the panel and runs the existing fly-to into `/mountains/[slug]`.
- Static mountains: terrain, fixed level, the display-marker line, and no pressure points or **Simulate**.
- Loading, error, and empty states from the addendum's States table.

**Done when.** Clicking Rainier opens the panel with the pins matching the list, a row click moves the selection, Escape restores the spinning globe, and **Open ranger view** lands on the mountain page with no jump cut.

## 30. Play the simulation in the panel

**Track.** Frontend.

**Outcome.** **Simulate** plays the flow on the map and the steps and callouts on the right.

**Build.**

- **Simulate** calls `POST /simulate`, follows the stream, and swaps the right column to the simulation view.
- Playback: one frame every 500 ms, replacing the flow fill at once. Dim the heat map to 35%. Mark each trail crossing when its step is reached. The camera does not move.
- Steps use the agent row glyphs, and the current one pulses. Callouts appear when their step is reached, with their audience labels. The method line always shows.
- **Replay** replays the loaded frames. **Back to pressure points** restores the list and the heat map.
- Reduced motion: final flow, all steps, and all callouts at once.

**Done when.** On Rainier, **Simulate** plays to the end in about 20 seconds, the flow reaches the trail step at the same moment its mark appears, at least one ranger callout and one public draft show, and a person who has not seen the app can follow it.

## 31. Wire the hill card to the run stream and the advisory

Track: frontend. Added late Sep 25, 2026, after the mountain page was rebuilt as the hill detail card.

**Done so far (Sep 26).** On a live mountain, **Analyze now** calls `POST /mountains/{slug}/analyze` and follows the run socket (`frontend/lib/pipeline/live-run.ts`, used by `usePipeline`). The seven API agents fold onto the five cards: Trail, History, and Route Scout share the Trails row. Reactive Measures come from the run advisory. Static mountains still use the scripted source in `frontend/lib/pipeline/orchestrator.ts`.

**Left.** `buildHillView()` in `frontend/lib/fixtures/hill-demo.ts` still supplies the trail scores, markers, overall score, mean slope, and preventative measures, and the card still says the scores are illustrative.

- **Trails.** Build `HillView.trails` from the scored catalog: the Route Scout's exposed trails, or `trailscan` scores served with the mountain. Put each marker at the trail's worst point. The slope and primary factor come from the terrain stats.
- **Honesty.** Drop the "Illustrative scores" line only for numbers that came from a run.

**Done when.** With the fake LLM server, one **Analyze now** on Rainier streams every agent into its card, the five trails and their markers match the advisory's scores, and the Reactive Measures come from the advisory. Unplugging the API mid-run shows the failure copy.

## 32. Build mountain data packs for the demo peaks

Track: ML and data, with small backend and frontend seams. Added Sep 26, 2026 so clicking a prepared peak on the globe gets the Rainier treatment instead of fixtures.

A pack reruns steps 10-14 and 19 for one more mountain, driven by the registry in `ml/scripts/mountain_packs.py`: DEM and WorldCover windows mosaicked from the same public COGs, the 30 m feature stack in the peak's own UTM zone, the knowledge-driven susceptibility index (never the Rainier LightGBM: its landslide labels are Rainier's), XYZ tiles, and OpenStreetMap trails via Overture with the longest named trail as the hero. Peaks: Mount Hood, Aconcagua, Matterhorn, Kilimanjaro, Mount Fuji, Mount Everest, Aoraki / Mount Cook. Rainier keeps its legacy paths and trained model; packs live under `packs/<slug>/` folders.

**Done when.** `python ml/scripts/build_pack.py <slug>` builds a pack end to end, the API serves that pack's tiles and trails by slug, and opening a packed peak in the browser shows its own heat map and trails with the index labeled as an index. A peak with no named trails shows an empty trail list, never Rainier's.

## Before the demo

Follow-up to steps 4 and 25. Not a numbered step.

- Provision Postgres on Neon or Supabase, set `DATABASE_URL`, then run `python -m app.schema && python -m app.seed` from `backend/`.
- Set `GEMINI_API_KEY` and `XAI_API_KEY`. Run `python -m app.agents.pipeline` once, then one **Analyze now** from the browser.
- Rehearse the demo script in `TerraSense.md` three times. Keep one finished run on screen as a fallback.

**Done when.** A live run with real keys has finished twice, and a person who has not seen the app can follow the demo script to the Reactive Measures.

---

# Part 2: Done

What each finished step shipped and how it was checked. File-level detail is in [docs/CODE_REFERENCE.md](docs/CODE_REFERENCE.md). Where a step's original plan changed, the change is noted.

## Since the numbered steps

Work that landed on Sep 25, 2026 after step 25, outside the numbered steps.

- **Seven-agent pipeline and the advisory** (backend). The five analysts run in parallel: Terrain, Weather, Trail, History, and Route Scout. The Risk Synthesizer then decides the severity, the action, three routes to avoid, three safe routes, and the ranger response. `advisory.py` checks its answer. Then the Alert Writer runs. `trailscan.py` scores every mapped trail. The run ends in an `Advisory` (`GET /runs/{id}/advisory`, `GET /mountains/{slug}/advisory`). Open-Meteo also feeds conditions (temperature, freeze-thaw, snowfall, wind, soil moisture, freezing level).
- **Contract audit** (PR #6). Tests pin the Model B seam, the provider schemas, and JSON-native payloads. Fixed fabricated soil-moisture zeros and the providers' `.env` loading. 204 pytest tests pass.
- **Hill detail card** (PR #5). The mountain page is two columns:
  - Map about 55%, with lettered markers A–E, tooltips, and **View** fly-to.
  - Panel about 45%, with stats, the overall score, the top five trails, preventative measures, and an Orchestrator with five agent cards and inline traces.

  **Analyze now** runs a scripted client-side orchestrator. Removed: the rain section, the ranger panel, the agent rows, and the reasoning side panel.
- **Panel and map pass** (PR #7). Larger panel text. Reactive Measures became their own section; on Sep 26 they were re-clustered by timing (now, 1 h, 6 h, 24 h), with the kind of work as a label on each card. The map opens framed from the summit elevation, orbits while idle, and limits zoom-out.
- **Light home and globe.** A light home theme and an evenly lit Earth. Mountain-logo markers replace the dots, and High and Extreme mountains keep a larger translucent sphere.
- **Gray mountain.** The map tints the mountain gray and fades its surroundings to white, using the same elevation footprint as the framing.
- **Mountain catalog** (Sep 26). `data/seed/mountains.json` holds 648 peaks. The default `SEED_MODE=mountainstest` loads 138 from `data/seed/mountains_test.json`. The globe draws 50 unless `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` changes. Fetch and selection live in `backend/app/mountain_catalog.py`. See [docs/seeding-and-catalog.md](docs/seeding-and-catalog.md).
- **Live hill-card agents** (Sep 26, part of step 31). **Analyze now** on Mount Rainier streams the seven agents into the five cards and fills Reactive Measures from the advisory. Trail scores on the card are still the illustrative fixture.
- **Production 72-hour classifier (new risk track).** Added a separate `(1 km cell, reference timestamp)` contract for rainfall-triggered landslide probability, direct NASA CSV/GeoJSON event ingestion, cell-aggregated static features, leakage-aware normalized observation/forecast samples, spatiotemporal LightGBM training, held-out calibration and target-precision thresholds, OOD/quality abstention, a backtest CLI, and `POST /api/v1/landslide-risk`. The checked-in API remains fail-closed until real timestamped IMERG/ERA5-Land/forecast inputs and calibrated artifacts are built; no performance numbers are fabricated.

Checked with `npm run lint`, `npm run typecheck`, `pytest`, and headless Chrome walks of the globe and the card.

## 1. Lay out the repo and environment

**Shipped.** `backend/`, `ml/scripts/`, `ml/artifacts/`, `data/seed/`. A `.gitignore` for `data/raw/`, `data/processed/`, `.env`, `ml/artifacts/*.tif`, `backend/tiles/`, and virtualenvs. A root `.env.example` with every variable and a comment each (`DATABASE_URL`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAPBOX_TOKEN`, the Gemini and xAI keys and models, and the optional LLM knobs). A root README with the dev commands.

**Done when.** A new shell can read `.env.example` and name the folder for the UI, the API, and the offline model.

## 2. Apply the dark dispatch theme

**Shipped.** Tokens in `frontend/app/globals.css` with shadcn role names, mirrored in `frontend/lib/theme.ts`, using the current Design Language values (basalt and glacier). The four risk colors are reserved for risk. Geist and Geist Mono are loaded. The home page is a full-bleed dark screen.

**Changed.** The original plan's hex values were replaced by the Design Language values in `TerraSense.md`.

**Done when.** The home page is a full-bleed dark screen with the TerraSense name in the top left and no light-theme chrome.

## 3. Stand up the FastAPI service

**Shipped.** `backend/app/main.py` with `GET /health`, CORS for `localhost:3000` plus `CORS_ORIGINS`, and a 503 when the database is down. Runs on port 8000.

**Done when.** `curl localhost:8000/health` returns a JSON ok payload, and the browser shows no CORS error.

## 4. Create the Postgres schema

**Shipped.** `backend/app/schema.sql` with the six tables, geometry as `jsonb`, and CHECK constraints. `python -m app.schema [--reset]` applies it. `hazards` later gained `trail_id`, `start_mile`, `end_mile` (step 18) and `bypass` (step 19).

**Done when.** All six tables exist, and a fresh database can be recreated from `schema.sql`. Verified on a local Postgres 16. No hosted database yet (see [Before the demo](#before-the-demo)).

## 5. Seed mountains and empty Rainier trails

**Shipped.** `data/seed/mountains.json` (Mount Rainier live with a placeholder `moderate`, Huascarán `high`, Mount Fuji `low`) and `backend/app/seed.py`, which upserts mountains, trails, and segments.

**Done when.** The `mountains` table has three rows and Rainier has trail rows.

## 6. Ship the mountain read API

**Shipped.** `GET /mountains` and `GET /mountains/{slug}` with trails, ordered segments, `active_hazard`, `historical_events`, and `active_run_id`. Static mountains return their seed risk.

**Done when.** `GET /mountains` returns three mountains and `GET /mountains/mount-rainier` returns the seeded trails.

## 7. Add the typed frontend API client

**Shipped.** `frontend/lib/types.ts` mirrors `backend/app/models.py`. `frontend/lib/api.ts` covers every endpoint. `frontend/lib/fixtures/run.json` holds one finished five-agent run, checked at import.

**Done when.** The home page reads three mountains from the API, and the fixture type-checks as `AgentEvent[]`.

## 8. Render the 3D globe and risk markers

**Shipped.** A custom React Three Fiber globe (`frontend/components/globe/`) with a textured Earth, an atmosphere rim, idle spin, drag, and zoom. Three markers in their risk colors, with a ring for the live one and a hover card.

**Done when.** The globe spins, drag and zoom work, and the three markers show the risk colors from the database.

## 9. Search, fly to a mountain, and open its page

**Shipped.** A centered combobox search ("mt" matches "mount"). A 1.5 s great-circle flight that fades to the background and routes to `/mountains/[slug]`. Loading, error, and not-found pages.

**Done when.** Search and click both land on `/mountains/mount-rainier` after a single camera move, with no jump cut.

## 13. Render susceptibility map tiles

**Shipped.** `backend/app/ml/tiles.py` (the shared tiler) and `ml/scripts/render_tiles.py`: 383 PNG tiles, z10 to z14, on the stepped four-color ramp, in about 3.5 s. `GET /mountains/{slug}/layers/susceptibility` returns the template.

**Changed.** The ramp uses the four risk colors with Low transparent (design addendum), not blue-green to red.

**Done when.** A tile URL shows a transparent PNG, and the template uses `{z}/{x}/{y}`.

## 15. Open the Mapbox mountain view

**Shipped.** `frontend/components/map/terrain-map.tsx`: MapLibre GL with AWS Terrain Tiles, exaggeration 1.5, a light shaded relief (Mapbox satellite with a token), all trails, and the hero trail. The ranger panel sits on the right.

**Changed.** MapLibre replaced Mapbox GL, so no token is required.

**Done when.** The Rainier page shows 3D terrain and the trail lines, and the panel matches the API record.

## 16. Toggle susceptibility and historical pins

**Shipped.** `frontend/components/map/layer-toggles.tsx` over the lower left of the map. Susceptibility appears at once and hides the heat map while on. The historical pin layer and popups are built, and the toggle is disabled until step 10's points exist.

**Changed.** No 400 ms fade on susceptibility (design addendum, Motion).

**Done when.** Both toggles work, pins open a small popup, and the raster lines up with the ridges.

## 18. Draw the heat map, hazard polygon, and trail risk

**Shipped.** `backend/app/ml/probability.py` (the Model B seam), `backend/app/ml/hazard.py`, and `backend/app/assessment.py`: probability tiles as the default layer with a 600 ms fade, per-segment risk on the hero trail, the flagged mile range, and one hazard polygon within 250 m of it.

**Changed.** Until step 17 lands, the probability map is the susceptibility stand-in, labeled everywhere.

**Done when.** The default map shows the heat map and a trail that changes color along its length, and one polygon exists for the worst cluster.

## 19. Add one bypass around the worst segment

**Shipped.** `ml/scripts/build_trail_network.py` writes `data/seed/trail_network.geojson`. `backend/app/bypass.py` routes the detour with the least walking plus trail given up, with high ground penalized. It returns name, via, miles, added distance and climb, a line, and per-piece levels, or None when the answer is to turn back.

**Done when.** The API returns a bypass name, added distance, added elevation, and a line that does not overlap the worst segment.

## 20. Define agent schemas, tools, and prompts

**Shipped.** `backend/app/agents/`: closed Pydantic schemas for the five agents, four fact-only tools, prompts following the design addendum's copy rules, the Gemini and Grok providers, and the router with every rule recorded in the trace.

**Done when.** Each schema rejects a missing field, and each tool returns data for `mount-rainier` with no LLM call (`backend/tests/test_agent_schemas.py`, `test_tools.py`, `test_router.py`, `test_providers.py`).

## 21. Run the five-agent pipeline

**Changed later.** The pipeline now runs seven agents. See [Since the numbered steps](#since-the-numbered-steps).

**Shipped.** `backend/app/agents/pipeline.py`: Terrain and Weather together, then Trail, Synthesizer, Writer. Retries, repair rounds, fallback provider, code-set confidence (0.40, 0.35, 0.25), `needs_review`, and copy checks with plain templates as the last resort.

**Done when.** `python -m app.agents.pipeline` prints five JSON objects, a final severity, and both texts. Checked against `backend/tests/fake_llm.py`. No live provider call has run yet.

## 22. Expose analyze, run status, and the live stream

**Shipped.** `backend/app/runs.py` and `backend/app/routes/runs.py`: `POST /mountains/{slug}/analyze` (409 for static), `GET /runs/{run_id}`, and `WS /runs/{run_id}/stream`. A finished run commits tiles, segment risk, the hazard, and the mountain's level in one transaction. A failed run writes none of that.

**Done when.** A socket client sees Terrain and Weather start together, then the later agents, then a completed `GET /runs/{run_id}` (`backend/tests/test_runs_api.py`).

## 23. Show the agent stream and the hazard panel

**Changed later.** The hill detail card replaced the ranger panel, the agent rows, and the reasoning panel. `lib/run-stream.ts` is kept for step 31.

**Shipped.** `frontend/components/mountain/mountain-dashboard.tsx`, `frontend/components/panel/` (ranger panel, hazard block, agent rows, level word), and `frontend/lib/run-stream.ts`, which reconnects twice before calling a run lost. Also the reasoning panel (team decision, Sep 25, 2026).

**Done when.** One click on Rainier streams all five rows and opens a pin whose four fields match the saved hazard.

## 24. Post the ranger alert to Discord (dropped)

Dropped by the team on Sep 25, 2026. A run posts nothing outside the app, and the mountain page has no `?hazard=` deep link. The ranger reads the alert in the app. The `alerts` table stays in the schema, unused.

## 25. Show the hiker card and rehearse the demo

**Changed later.** The hiker card and the hazard block are not rendered on the hill detail card. Their components and `GET /forecast` are kept.

**Shipped.** `GET /forecast` (`backend/app/routes/forecast.py`) and `frontend/components/panel/hiker-card.tsx`, with the bypass drawn dashed on the map. Empty, loading, and error states for the globe, the mountain, and the run.

**Done when.** A person who has not seen the app can follow the demo script to the reasoning panel and a hiker card that names the bypass. Walked in Chromium against the fake LLM APIs. The live-key rehearsal is under [Before the demo](#before-the-demo).
