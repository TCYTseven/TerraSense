# Code reference

Map of the TerraSense repo. Update the matching section in the same change that adds, renames, or deletes a file.

Planned paths are labeled **planned**. They are not in the tree yet. Do not import them. When you create one, remove the planned label and document the real exports.

The product contract is [`../TerraSense.md`](../TerraSense.md). The build order is [`../implementation-steps.md`](../implementation-steps.md).

## What is in the tree

```
frontend/          Next.js app. Runs with npm run dev.
backend/           FastAPI service: health, mountain reads, schema, seed.
ml/scripts/        Offline scripts: download_sources.py (step 10).
ml/artifacts/      Model outputs: metrics.json, feature_importance.json (the .tif is gitignored).
data/seed/         Committed seed files: mountains, trails.
context/           Spec and the 25 implementation steps.
context/docs/      Team brief, handoff, UX, this file.
.claude/agents/    Subagent definitions: one builder per track and a reviewer.
AGENTS.md          Agent guide: folder owners, team rules, shared facts.
README.md          Pitch, the three commands, folder owners.
.env.example       Every environment variable, with a comment. CORS_ORIGINS is optional.
.gitignore         Ignores .env, data/raw/, data/processed/, ml/artifacts/*.tif, virtualenvs.
```

## Agent harness

Basic scaffolding so several coding agents can split the work. Update the matching guide when a folder's commands or rules change.

| File | What it is |
|---|---|
| `AGENTS.md` | Repo-wide guide: read order, folder owners, team rules, shared facts. |
| `CLAUDE.md` | `@AGENTS.md`, so Claude Code loads the same guide. Each folder below has one too. |
| `frontend/AGENTS.md` | The `next dev` managed block, then TerraSense frontend steps, commands, and rules. |
| `backend/AGENTS.md` | Backend steps, rules, and commands. |
| `ml/AGENTS.md` | ML steps, one script per step, modeling rules. |
| `data/AGENTS.md` | What is committed versus gitignored, seed files, data rules. |
| `.claude/agents/frontend-builder.md` | Subagent that builds one frontend step. |
| `.claude/agents/backend-builder.md` | Subagent that builds one backend step. |
| `.claude/agents/ml-data-builder.md` | Subagent that builds one ML or data step. |
| `.claude/agents/step-reviewer.md` | Read-only subagent that checks a finished step against its "Done when". |

## Frontend (exists)

Next.js 16.3.6, React 19.2, Tailwind CSS 4, App Router, TypeScript. Package name `frontend`.

| File | What it is |
|---|---|
| `frontend/package.json` | Scripts: `dev`, `build`, `start`, `lint`, `typecheck` (`next typegen && tsc --noEmit`, which works on a fresh clone). Dependencies: Next, React, React DOM, `three`, `@react-three/fiber`, `@react-three/drei`. |
| `frontend/app/layout.tsx` | Root layout, full height. Loads Geist (UI) and Geist Mono (numbers) as CSS variables. Sets metadata and a dark `viewport`. |
| `frontend/app/page.tsx` | Home: the full-screen globe with the TerraSense name at the top left. |
| `frontend/app/mountains/[slug]/page.tsx` | Mountain page, server-rendered from `GET /mountains/{slug}`: map area (about 70%, a coordinate placeholder until the Mapbox view in step 15) and the ranger panel with name, region, elevation, summit, overall risk, and last refresh. **Analyze now** renders only when `is_live` (disabled until step 23). Static mountains show a fixed-risk note. Fades in. |
| `frontend/app/mountains/[slug]/loading.tsx` | Plain dark screen while the page loads. Lets the globe prefetch the route. |
| `frontend/app/mountains/[slug]/error.tsx` | API failure: message, **Try again** (`retry()` refetches), link back to the globe. |
| `frontend/app/mountains/[slug]/not-found.tsx` | Unknown slug. |
| `frontend/app/not-found.tsx` | Site-wide dark 404. |
| `frontend/app/globals.css` | Dark dispatch tokens as Tailwind colors: `background`, `surface`, `panel`, `line`, `foreground`, `muted`, `accent`, and `risk-low`, `risk-moderate`, `risk-high`, `risk-extreme`. Font tokens `sans` and `mono`. `animate-fade-in` and the `bg-grid` utility. Dark base styles. |
| `frontend/app/icon.svg` | Favicon. |
| `frontend/lib/theme.ts` | `THEME` and `RISK_COLORS` (keyed by `RiskLevel`): the same palette for WebGL code. Mirrors `globals.css`. |
| `frontend/lib/types.ts` | Mirrors `backend/app/models.py`: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard`, `RiskLevel` (with `RISK_LEVELS`), `HazardType`, `LineString`, `Polygon`, `Position`. Stream types: `AgentEvent`, `AgentName` (`AGENT_NAMES`), `AgentStatus` (`AGENT_STATUSES`). |
| `frontend/lib/api.ts` | `API_URL` from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). `getMountains(init?)`, `getMountain(slug, init?)` (null on 404), `ApiError` with `status`. Requests use `cache: "no-store"`. |
| `frontend/lib/agent-events.ts` | `isAgentEvent(value)` and `parseAgentEvents(value)`: runtime checks for JSON that claims to be `AgentEvent`s. |
| `frontend/lib/fixtures/run.json` | One finished five-agent run, 10 events in stream order. Illustrative values: Skyline Trail miles 1.2 to 2.1, bypass Golden Gate Trail, severity high, confidence 0.81. |
| `frontend/lib/fixtures/index.ts` | `FIXTURE_RUN: AgentEvent[]`, parsed from `run.json`. Throws on import if the file drifts. |
| `frontend/components/globe/globe-view.tsx` | The globe screen. Loads the globe with `ssr: false`, fetches `GET /mountains`, shows an alert with Retry when the API is unreachable, and renders the search. A marker click or a search pick prefetches `/mountains/[slug]`, starts the fly-to, fades to the background over the last 300 ms, then pushes the route. Before the textured globe is ready, a pick opens the page directly. |
| `frontend/components/globe/spinning-globe.tsx` | React Three Fiber canvas: textured Earth, atmosphere rim, idle spin, drag and zoom. Takes `mountains`, `flyTarget`, `onSelect`, `onArrive`, `onReady` (fires once the textured Earth mounts). Renders one marker each inside the rotating Earth mesh. Owns hover state and pauses the spin while a marker is hovered or the camera flies. Disables the orbit controls during a flight. The Earth mesh stops pointer events so far-side markers cannot be hovered or clicked. |
| `frontend/components/globe/camera-flight.tsx` | `CameraFlight`: starts on the first frame where the target and the Earth mesh both exist, then makes an eased great-circle move from the current view to face the target in `FLY_DURATION_MS`, ending 0.45 above the surface, with a slight outward arc on long hops. Calls `onArrive`. Instant under reduced motion. |
| `frontend/components/globe/motion.ts` | `FLY_DURATION_MS` (1500) and `FADE_OUT_MS` (300), shared by the flight and the fade overlay. |
| `frontend/components/globe/mountain-search.tsx` | Centered combobox. `matchMountains(mountains, query)` ignores case and accents and expands "mt" to "mount". Arrow keys, Enter, Escape, and click. Lists every mountain on focus. `emptyMessage` covers loading and API failure. |
| `frontend/components/globe/mountain-marker.tsx` | One marker: unlit dot and halo in the risk color, an extra ring for live mountains, an invisible hit sphere, and a hover card (name, elevation, region, risk, last refresh) anchored with drei `Html`. Fades out near the horizon so no marker floats past the globe's edge. Hover is checked on pointer over and move, so a marker that turns toward a resting pointer still hovers. A click (under 5 px of drag) on a marker that faces the camera calls `onSelect`. |
| `frontend/components/globe/geo.ts` | `latLonToVector3(lat, lon, radius)`: a point on a three.js SphereGeometry that matches the equirectangular texture. |
| `frontend/components/risk-badge.tsx` | `RiskBadge`: risk-colored dot plus "High risk" style label. |
| `frontend/lib/format.ts` | `riskLabel`, `formatUtc` ("Sep 25, 10:50 UTC"), `refreshLabel` (last analysis, "Not analyzed yet", or "Static marker, fixed risk"), `formatElevation`, `formatLatLon` ("46.8523° N, 121.7603° W"). |
| `frontend/public/globe/` | `earth-day.jpg` (4096×2048 color) and `earth-topology.png` (2048×1024 bump map). |
| `frontend/next.config.ts` | Loads the repo root `.env` with `process.loadEnvFile` so the app and the API share one file. Variables already set win. |
| `frontend/postcss.config.mjs` | Tailwind PostCSS plugin. |
| `frontend/tsconfig.json` | Strict TypeScript. Path alias `@/*` → repo root of `frontend/`. |
| `frontend/eslint.config.mjs` | `eslint-config-next`. |

Routes: `/` (globe) and `/mountains/[slug]`.

## Backend (exists)

FastAPI on Python 3.11. Run from `backend/` with `uvicorn app.main:app --reload --port 8000`.

| File | What it is |
|---|---|
| `backend/requirements.txt` | FastAPI, Uvicorn, Pydantic, HTTPX, psycopg 3 with `psycopg-pool`, `python-dotenv`. Compatible-release pins. |
| `backend/app/__init__.py` | Package marker. |
| `backend/app/main.py` | `app`. CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` for GET and POST. Plus any origins in `CORS_ORIGINS`. Mounts the mountains router. A pool timeout or connection error returns 503 `{"detail": "Database unavailable"}`. `GET /health` returns `{"status": "ok"}` without touching the database. |
| `backend/app/config.py` | Loads the repo root `.env`. `database_url()` returns `DATABASE_URL` or raises with the fix. `cors_origins()` reads extra origins from `CORS_ORIGINS`. `REPO_ROOT`. |
| `backend/app/db.py` | `connect()` opens one psycopg connection for scripts. `get_pool()` makes the API's pool on first use, under a lock (dict rows, connections checked before use so hosted Postgres idling is safe, `POOL_TIMEOUT_S` = 5 s wait). `get_conn()` is the FastAPI dependency. `close_pool()` runs at shutdown. |
| `backend/app/schema.sql` | Six tables: `mountains`, `trails`, `trail_segments`, `analysis_runs`, `hazards`, `alerts`. UUID keys, geometry as `jsonb`, CHECK constraints for risk levels, run status, hazard type, and alert action. Every statement is `IF NOT EXISTS`. |
| `backend/app/schema.py` | `python -m app.schema [--reset]`. `apply_schema(reset)` runs `schema.sql` and returns the tables present. `--reset` drops the six tables first. |
| `backend/app/seed.py` | `python -m app.seed`. `load_mountains(conn)` upserts `data/seed/mountains.json` by slug. The seed risk applies only while `last_analyzed_at` is null. `load_trails(conn)` upserts `data/seed/trails.geojson` by mountain and name, removes every trail the file no longer lists (for all mountains), and rejects a name repeated for one mountain. |
| `backend/app/models.py` | Pydantic response models: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard`, plus `RiskLevel`, `HazardType`, `Geometry`. `frontend/lib/types.ts` mirrors them. |
| `backend/app/routes/mountains.py` | `GET /mountains`: every mountain, live first. `GET /mountains/{slug}`: the mountain, its trails with ordered segments, and `active_hazard` (latest by `created_at`, or null). 404 for an unknown slug. Steps 13 and 18 add the layer endpoint here. |

### API responses

`GET /mountains` returns `Mountain[]`. `GET /mountains/{slug}` returns `MountainDetail`. IDs are UUID strings, times are ISO 8601 with a timezone, geometry is a GeoJSON geometry object.

```
Mountain       { id, name, slug, lat, lon, elevation_m, region, current_risk_level, last_analyzed_at | null, is_live }
MountainDetail   Mountain + { trails: Trail[], active_hazard: Hazard | null }
Trail          { id, name, geom (LineString), length_km | null, elevation_gain_m | null, segments: TrailSegment[] }
TrailSegment   { id, seq, geom (LineString), start_mile, end_mile, risk_level | null, probability | null }
Hazard         { id, run_id | null, type (landslide | debris_flow), severity, probability, confidence | null,
                 geom (Polygon), drivers: string[], what | null, why | null, how_to_avoid | null, needs_review, created_at }
```

## Data and ML (exists)

| File | What it is |
|---|---|
| `data/seed/mountains.json` | Mount Rainier (`is_live: true`, placeholder risk `moderate`), Huascarán (`high`), Mount Fuji (`low`). Fields in `data/AGENTS.md`. |
| `data/seed/trails.geojson` | One rough Skyline Trail loop at Paradise for Rainier, 17 points. NPS length 8.9 km, gain 518 m. Step 14 replaces the line. |
| `data/AGENTS.md` | Seed formats and data rules. |
| `data/seed/sources.md` | URL, access date, licence, grid, and checks for each step 10 file. The landslide entry is pending, with the command that finishes it. |
| `data/raw/rainier_dem_cop30.tif` | Gitignored. Copernicus DEM GLO-30 clipped to the bbox, EPSG:4326, 1405 x 721 px. Rebuild with the step 10 script. |
| `data/raw/rainier_landcover_worldcover2021.tif` | Gitignored. ESA WorldCover 2021 class codes clipped to the bbox, EPSG:4326, 4680 x 2400 px. |
| `ml/requirements.txt` | `rasterio`, `numpy` (below 2.4 for pysheds), `requests`, `scipy`, `pandas`, `pyarrow`, `pysheds` for the offline scripts. |
| `ml/scripts/build_features.py` | Step 11. `python ml/scripts/build_features.py [--landslides PATH]`. Builds a 30 m grid in UTM zone 10N (1004 x 757 cells) and writes `data/processed/features.tif` with seven bands: elevation, Horn slope, aspect (compass bearing, NaN on flats), Zevenbergen-Thorne curvature (negative = concave), distance to drainage (D8 channels at 0.2 km2, via pysheds), WorldCover land cover (mode resampled), and topographic wetness index. When landslide points exist it writes `data/processed/features.parquet`: positives within 50 m of `exact` or `1km` points, negatives 1:3 from ground over 500 m away, `label`, `region` (7.5 km blocks), `row`, `col`. |
| `data/processed/features.tif` | Gitignored. The step 11 feature stack. |
| `ml/scripts/train_susceptibility.py` | Step 12. `python ml/scripts/train_susceptibility.py [--table PATH] [--artifacts DIR]`. With the labeled table: LightGBM, held-out spatial regions (at least 20% of positives), AUC and precision at 0.45, gain importance, refit on all rows, full-map prediction. Without it: a knowledge-driven index (weights in `INDEX_WEIGHTS`, stretched between the 2nd and 98th percentile of the box) and `trained: false`. |
| `ml/artifacts/metrics.json` | Method, `trained`, AUC, precision at the high threshold, map summary. Committed so the current status is visible. |
| `ml/artifacts/feature_importance.json` | Gain importance (LightGBM) or the index weights. |
| `ml/artifacts/susceptibility.tif` | Gitignored. 0-1 susceptibility on the 30 m UTM grid. Input to tiles (step 13) and Model B (step 17). |
| `ml/artifacts/susceptibility_lgbm.txt` | The trained model, written only when labels exist. |
| `ml/scripts/download_sources.py` | Step 10. `python ml/scripts/download_sources.py [--only dem,landcover,landslides] [--force] [--glc-csv URL_OR_PATH]`. Reads the bbox window of the Copernicus DEM and ESA WorldCover COGs over HTTP ranges, writes `data/raw/`, and prints a check that each file covers the bbox. Filters the NASA Global Landslide Catalog CSV to the bbox into `data/seed/landslides.geojson`. A failed stage does not stop the others. |

## Planned layout

Create these as the steps call for them. Paths match [`../implementation-steps.md`](../implementation-steps.md).

### Frontend

| Path | Step | Role |
|---|---|---|
| `frontend/components/map/` | 15–16, 18 | Mapbox terrain, tiles, trails, pins. Mounts in the map area of `/mountains/[slug]` |
| `frontend/components/panel/` | 23, 25 | Side panel, agent rows, hazard detail, hiker card |

`AgentEvent` shape, fixed in step 7 (`frontend/lib/types.ts`):

```json
{ "run_id": "", "agent": "terrain|weather|trail|synthesizer|writer", "status": "waiting|running|done|error", "summary": "", "payload": {} }
```

### Backend

| Path | Step | Role |
|---|---|---|
| `backend/app/ml/model_b.py` | 17 | Susceptibility plus Open-Meteo rain |
| `backend/app/agents/` | 20–21 | Schemas, tools, five agents, orchestrator |
| `backend/app/alerts/discord.py` | 24 | Webhook post |
| `backend/tiles/` | 13, 18 | XYZ PNGs for susceptibility and probability |

API the frontend should call, from the spec:

```
GET  /health
GET  /mountains
GET  /mountains/{slug}
GET  /mountains/{slug}/layers/{layer}
POST /mountains/{slug}/analyze          → { run_id }
GET  /runs/{run_id}
WS   /runs/{run_id}/stream
GET  /forecast?mountain_id&trail_id
```

`POST /analyze` is rejected when `is_live` is false.

### Data and ML

| Path | Step | Role |
|---|---|---|
| `data/seed/landslides.geojson` | 10, 14 | Pin source. Pending: `download_sources.py --only landslides` needs data.nasa.gov |
| `ml/scripts/render_tiles.py` | 13, 18 | XYZ tiles in EPSG:3857 |

## Invariants

- Risk levels are `low`, `moderate`, `high`, `extreme`.
- Bins: low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7.
- Rainier bbox: west -121.93, south 46.76, east -121.54, north 46.96.
- Tiles are Web Mercator XYZ. A tile that is offset from the ridges is a broken step 13 or 18, not a Mapbox setting to tweak later.
- Agents return Pydantic-validated JSON. Tools return precomputed facts. They do not scan the raster and they do not invent trail geometry.
