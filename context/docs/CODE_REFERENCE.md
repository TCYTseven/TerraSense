# Code reference

Map of the TerraSense repo. Update the matching section in the same change that adds, renames, or deletes a file.

Planned paths are labeled **planned**. They are not in the tree yet. Do not import them. When you create one, remove the planned label and document the real exports.

The product contract is [`../TerraSense.md`](../TerraSense.md). The build order is [`../implementation-steps.md`](../implementation-steps.md).

## What is in the tree

```
frontend/          Next.js app. Runs with npm run dev.
backend/           FastAPI service: health, mountain reads, schema, seed, the step 18 assessment.
ml/scripts/        Offline scripts, one per step: downloads, features, model, tiles, trails.
ml/artifacts/      Model outputs: metrics.json, feature_importance.json (the .tif is gitignored).
data/seed/         Committed seed files: mountains, trails, the hero trail's segments, the bypass network.
context/           Spec and the 25 implementation steps.
context/docs/      Team brief, handoff, UX, this file.
.claude/agents/    Subagent definitions: one builder per track and a reviewer.
AGENTS.md          Agent guide: folder owners, team rules, shared facts.
README.md          Pitch, the three commands, folder owners.
.env.example       Every environment variable, with a comment. CORS_ORIGINS, OPEN_METEO_FIXTURE, and the LLM tuning knobs are optional.
.gitignore         Ignores .env, data/raw/, data/processed/, ml/artifacts/*.tif, backend/tiles/, frontend/public/maplibre/, virtualenvs.
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
| `frontend/package.json` | Scripts: `dev`, `build`, `start`, `lint`, `typecheck` (`next typegen && tsc --noEmit`, which works on a fresh clone), `postinstall` (copies the MapLibre worker). Dependencies: Next, React, React DOM, `three`, `@react-three/fiber`, `@react-three/drei`, `maplibre-gl`. |
| `frontend/app/layout.tsx` | Root layout, full height. Loads Geist (UI) and Geist Mono (numbers) as CSS variables. Sets metadata and a dark `viewport`. |
| `frontend/app/page.tsx` | Home: the full-screen globe with the TerraSense name at the top left. |
| `frontend/app/mountains/[slug]/page.tsx` | Mountain page, server-rendered: `GET /mountains/{slug}` and, for live mountains, the probability and susceptibility layers (a failed layer leaves the map without it) and the run to show (the one going now, or the one behind the active hazard). Hands them to `MountainDashboard`. |
| `frontend/app/mountains/[slug]/loading.tsx` | Plain dark screen while the page loads. Lets the globe prefetch the route. |
| `frontend/app/mountains/[slug]/error.tsx` | API failure: message, **Try again** (`retry()` refetches), link back to the globe. |
| `frontend/app/mountains/[slug]/not-found.tsx` | Unknown slug. |
| `frontend/app/not-found.tsx` | Site-wide dark 404. |
| `frontend/app/globals.css` | Basalt and glacier tokens with the shadcn role names from the design addendum (`--background`, `--muted`, `--card`, `--popover`, `--secondary`, `--foreground`, `--muted-foreground`, `--primary`, `--ring`, `--border`, `--input`, `--accent`, `--destructive`), mapped to Tailwind colors, plus `risk-low`, `risk-moderate`, `risk-high`, `risk-extreme`. Font tokens `sans` and `mono`. `animate-fade-in`, `animate-work` (the work pulse for running rows), and the `bg-grid` utility. `.terra-popup` puts MapLibre popups on the panel surface. Dark base styles. |
| `frontend/app/icon.tsx` | Favicon, generated with `ImageResponse` from `THEME` colors. |
| `frontend/lib/theme.ts` | `THEME` (neutral and accent hex values by role) and `RISK_COLORS` (keyed by `RiskLevel`) for WebGL, Mapbox, and the app icon. Mirrors `globals.css`. |
| `frontend/lib/types.ts` | Mirrors `backend/app/models.py`: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard` (with `trail_id`, `trail_name`, `start_mile`, `end_mile`, `bypass`), `Bypass`, `BypassPiece`, `HistoricalEvent`, `RiskLevel` (with `RISK_LEVELS`), `HazardType`, `LineString`, `Polygon`, `Position`, `LayerTiles`. Stream types: `AgentEvent` (with an optional `trace`), `AgentName` (`AGENT_NAMES`), `AgentStatus` (`AGENT_STATUSES`), and for the reasoning panel `AgentTrace`, `RouteDecision`, `RouteRule`, `ToolCall`, `Attempt`, `Usage`, `ProviderName` (`PROVIDER_NAMES`), and for step 22 `Run`, `RunUpdate`, `RunStatus` (`RUN_STATUSES`), `RunPhase`, `RainTotals`, and `MountainDetail.active_run_id`. |
| `frontend/lib/api.ts` | `API_URL` from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). `getMountains(init?)`, `getMountain(slug, init?)` (null on 404), `getLayer(slug, layer, init?)` (null on 404), `startAnalysis(slug)` (the run id; an error carries the API's `detail`), `getRun(runId)` (null on 404), `runStreamUrl(runId)`, `ApiError` with `status`. Requests use `cache: "no-store"`. |
| `frontend/lib/agent-events.ts` | `isAgentEvent(value)` and `parseAgentEvents(value)`: runtime checks for JSON that claims to be `AgentEvent`s, including the parts of a `trace` the reasoning panel reads. `isRunUpdate(value)` for the stream's run messages. |
| `frontend/lib/fixtures/run.json` | One finished five-agent run, 10 events in stream order. Illustrative values: Skyline Trail miles 1.2 to 2.1, bypass Golden Gate Trail, severity high, confidence 0.81. |
| `frontend/lib/fixtures/index.ts` | `FIXTURE_RUN: AgentEvent[]`, parsed from `run.json`. Throws on import if the file drifts. |
| `frontend/lib/globe-display-mountains.ts` | `globeMountainLimit()` reads `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` (default 50; `0` = no cap). `selectGlobeMountains()` keeps live peaks and fills the cap with catalog peaks spread across a lat/lon grid (round-robin per cell, highest elevation first in each cell). |
| `frontend/components/globe/globe-view.tsx` | The globe screen. Loads the globe with `ssr: false`, fetches `GET /mountains`, shows spaced markers via `selectGlobeMountains`, search over the full list, an alert with Retry when the API is unreachable. A marker click or a search pick prefetches `/mountains/[slug]`, starts the fly-to, fades to the background over the last 300 ms, then pushes the route. Before the textured globe is ready, a pick opens the page directly. |
| `frontend/components/globe/spinning-globe.tsx` | React Three Fiber canvas: textured Earth (evenly lit: bright ambient and hemisphere light plus the day texture as a faint emissive layer, `EARTH_GLOW`), atmosphere rim, idle spin, drag and zoom. Takes `mountains`, `flyTarget`, `onSelect`, `onArrive`, `onReady` (fires once the textured Earth mounts). Renders one marker each inside the rotating Earth mesh. Owns hover state and pauses the spin while a marker is hovered or the camera flies. Disables the orbit controls during a flight. The Earth mesh stops pointer events so far-side markers cannot be hovered or clicked. |
| `frontend/components/globe/camera-flight.tsx` | `CameraFlight`: starts on the first frame where the target and the Earth mesh both exist, then makes an eased great-circle move from the current view to face the target in `FLY_DURATION_MS`, ending 0.45 above the surface, with a slight outward arc on long hops. Calls `onArrive`. Instant under reduced motion. |
| `frontend/components/globe/motion.ts` | `FLY_DURATION_MS` (1500) and `FADE_OUT_MS` (300), shared by the flight and the fade overlay. |
| `frontend/components/globe/mountain-search.tsx` | Centered combobox. `matchMountains(mountains, query)` ignores case and accents and expands "mt" to "mount". Arrow keys, Enter, Escape, and click. Lists every mountain on focus. `emptyMessage` covers loading and API failure. |
| `frontend/components/globe/mountain-marker.tsx` | One marker: a camera-facing mountain logo (peaks in the risk color, white snowcap, dark outline) and a halo ring, a translucent risk-colored sphere centered on the logo for High and Extreme, an extra ring for live mountains (visual meshes skip raycasting), an invisible hit sphere, and a hover card (name, elevation, region, risk, last refresh) anchored with drei `Html`. Fades out near the horizon so no marker floats past the globe's edge. Hover is checked on pointer over and move, so a marker that turns toward a resting pointer still hovers. A click (under 5 px of drag) on a marker that faces the camera calls `onSelect`. |
| `frontend/components/globe/geo.ts` | `latLonToVector3(lat, lon, radius)`: a point on a three.js SphereGeometry that matches the equirectangular texture. |
| `frontend/components/risk-badge.tsx` | `RiskBadge`: risk-colored dot plus "High risk" style label. |
| `frontend/lib/format.ts` | `riskLabel`, `formatUtc` ("Sep 25, 10:50 UTC"), `refreshLabel` (last analysis, "Not analyzed yet", or "Static marker, fixed risk"), `formatElevation`, `formatMiles` (km to "5.5 mi"), `formatLatLon` ("46.8523° N, 121.7603° W"), `formatDate` ("2011-05-01" to "May 1, 2011"), `humanize` ("debris_flow" to "Debris flow"), and for the panel `formatFeet`, `formatScore`, `formatMileRange` ("mi 4.6–4.9"), `formatSignedMiles`, `formatSignedFeet`, `formatClock` ("14:05", local), `timeAgo` ("12 min ago"), `hazardLabel`. |
| `frontend/public/globe/` | `earth-day.jpg` (4096×2048 color) and `earth-topology.png` (2048×1024 bump map). |
| `frontend/next.config.ts` | Loads the repo root `.env` with `process.loadEnvFile` so the app and the API share one file. Variables already set win. |
| `frontend/postcss.config.mjs` | Tailwind PostCSS plugin. |
| `frontend/tsconfig.json` | Strict TypeScript. Path alias `@/*` → repo root of `frontend/`. |
| `frontend/eslint.config.mjs` | `eslint-config-next`. Ignores the copied worker in `public/maplibre/`. |
| `frontend/components/map/mountain-map.tsx` | `MountainMap`: loads the terrain map with `ssr: false`, showing the surface color meanwhile. |
| `frontend/components/map/terrain-map.tsx` | `TerrainMap({ name, lon, lat, elevationM, trails, isLive, probability, susceptibility, hazard, hazardSelected, onHazardClick, onMapClick, historicalEvents, trailMarkers?, focus? })`: (the hill card adds the lettered trail markers and camera focus via `useTrailMarkers`) the MapLibre map. 3D terrain, navigation and scale controls, a summit label on the terrain, and the trails from `GET /mountains/{slug}`, the hero trail colored by segment risk. Opens framed on the summit and the hero trail (or on the summit alone), pitched 55°. On live mountains: the 72-hour heat map as the default layer (step 18), fading in over 600 ms once its tiles load and again when its tiles change (instant under reduced motion; draped textures are redrawn each frame because MapLibre's terrain cache ignores paint changes); the hazard zone's 2 px outline in its level color and its pin (a button marker at a point inside the zone: level color, dark ring, warning triangle, an accent ring when selected; a click toggles the hazard and a click on the empty map closes it); the susceptibility raster, which hides the heat map while on (step 16, no fade); past landslide pins with a popup per pin (date, type, source; catalog text goes in as text, only http(s) links become links). Shows "Loading terrain…" until the map loads, and a message when WebGL is off or the map fails. |
| `frontend/components/map/map-style.ts` | `mountainStyle({summitM, lon, lat, mapboxToken})` tints the mountain gray above 50% of the summit and white below 42%, and adds `LAYER.surround`, a feathered white wash over the hillshade outside the footprint. `footprintRadiusKm(elevationM)`. `openingBounds(lon, lat, elevationM, points)`: the mountain's footprint, a radius of `FOOTPRINT_PER_M` (≈2.1) × elevation clamped to `FOOTPRINT_KM`, stretched to nearby trail markers. Adds `SOURCE.trailRisk`, `LAYER.trailRisk`, `trailRiskFeatures`, `trailRiskPaint(selected)` for the hill card's lettered trails. The style: AWS Terrain Tiles (Terrarium) for terrain, an elevation tint (`color-relief`, gray valleys to white summit) and hillshade for the light relief, or Mapbox satellite when `NEXT_PUBLIC_MAPBOX_TOKEN` is set. Trail layers: other trails thin and dashed, the hero trail's segments cased and colored by `risk_level` (ink while unscored). Exports `CAMERA`, `MAP_COLORS`, `SOURCE`, `LAYER`, `TERRAIN_EXAGGERATION`, `mountainStyle`, `trailFeatures`, `openingBounds`, `isHero`, for step 16 `rasterSource` (a `LayerTiles` as a raster source), `historyFeatures`, and `HISTORY_LAYER` (8 px pins in the text color with a dark ring, never a risk color), and for step 18 `HEAT_FADE_MS`, `hazardFeatures`, and `HAZARD_OUTLINE_COLOR`. |
| `frontend/components/map/layer-toggles.tsx` | `LayerToggles({ toggles, onToggle })`: the toggle group over the lower left of the map (step 16). Each toggle is a pressed/unpressed button; `unavailable` disables it and says why in its title. Hidden on static mountains. |
| `frontend/lib/hill.ts` | Hill card view model, independent of the data source: `HillView` (stats, overall score and level, top five `TrailRisk`s lettered A–E with slope, primary factor, marker center and zoom, preventative bullets, `isDemo`), `CameraFocus` (`{letter, nonce}` from **View**), and the pipeline types (`PIPELINE_AGENTS`, `PIPELINE_LABELS` with Mass Alert Writer, `PipelineStatus` idle/running/done/error, `PipelineAgentState` with its trace, `ReactiveMeasure` (category, title, detail, `timing`, letter), `MEASURE_CATEGORIES`/`MEASURE_CATEGORY_LABELS` (the card label) and `MEASURE_TIMINGS`/`MEASURE_TIMING_LABELS` (the clusters), `PipelineState`). |
| `frontend/lib/fixtures/hill-demo.ts` | `buildHillView(mountain)`: the mountain's real fields plus illustrative scores for five real Rainier trails (Kautz Creek, Van Trump, Comet Falls, Glacier Basin, Skyline) until the per-trail model lands. `levelForScore` (the shared bins), `RAINIER_BBOX`. Static mountains get no trails. |
| `frontend/components/hill/hill-card.tsx` | `HillCard`: the mountain page. Left 55% the 3D mountain view (`next/dynamic`, `ssr: false`), right 45% one scrolling panel: header, overall risk, top five trails, preventative measures, agents; **Analyze now** in a footer outside the scroll area. Holds the camera `focus` and `usePipeline(hill)`. Static mountains keep header and level only. |
| `frontend/components/hill/hill-header.tsx` | `HillHeader`: back link, name, one mono stats line (elevation ft, mean slope, area km²), region. |
| `frontend/components/hill/overall-risk.tsx` | `OverallRisk`: the score as a large mono number with `LevelWord` and the High/Extreme treatment; the illustrative-scores line when `isDemo`; the display-marker line for static mountains. |
| `frontend/components/hill/trail-list.tsx` | `TrailList`: five rows (badge, name, factor and slope, level dot and score, **View**). The last viewed row is marked selected. |
| `frontend/components/hill/trail-badge.tsx` | `TrailBadge`: the A–E circle in the trail's level color with a dark letter, matching the map marker. |
| `frontend/components/hill/preventative-measures.tsx` | `PreventativeMeasures`: three to five bullets. |
| `frontend/components/map/hill-mountain-view.tsx` | `HillMountainView`: fills the left column with `MountainMap` (trails, heat map, susceptibility, hazard outline) and passes the trail markers and camera focus. |
| `frontend/components/map/use-idle-orbit.ts` | `useIdleOrbit(map, focused)`: turns the bearing at `CAMERA.orbitDegPerSec` while the map is at rest; pauses while the pointer is over the map, waits `CAMERA.orbitResumeMs` after a pointer, wheel, or key input, stays off while a trail is focused or under reduced motion. |
| `frontend/components/map/use-trail-markers.ts` | `useTrailMarkers(map, trails, focus, onSelect?)`: with `onSelect` (TerrainMap's `onTrailSelect`), a click on a marker, a lettered line, or near a marker selects that trail so the parent flies there like View; one button `Marker` per trail, a shared hover/focus `Popup` (name, score and level, slope, primary factor) that also opens within 400 m of a region, lettered trail lines, the selected marker's accent ring, and `flyTo` (1.5 s, pitch 60; `jumpTo` under reduced motion) on each new focus nonce, pinning the tooltip on arrival. `trailAriaLabel`. |
| `frontend/lib/pipeline/orchestrator.ts` | `runPipeline(hill, onUpdate, signal, source?)`: Terrain, Weather, and Trails in parallel (`Promise.allSettled`), then Synthesizer, then Mass Alert Writer, then `measures`. A failure sets the orchestrator to error and leaves later agents idle; abort stops quietly. `AgentSource`/`AgentRunner` is the seam for a real stream adapter; `scriptedSource` and `createScriptedSource({failAgent, speed})` are the client-side stand-in. `initialPipelineState`. |
| `frontend/lib/pipeline/demo-traces.ts` | `scriptFor(agent, hill)`: 4–7 illustrative trace steps per agent built from the `HillView`. `demoMeasures(hill)`: an incident-style response (closures, sweeps and a shelter point, SAR staging, spotters and patrols, county and weather-service coordination, public drafts), each with a `timing` cluster. |
| `frontend/lib/pipeline/use-pipeline.ts` | `usePipeline(hill)`: `{state, running, analyze}`. `analyze` is ignored mid-run, resets, and starts; unmount aborts. |
| `frontend/components/pipeline/agent-pipeline.tsx` | `AgentPipeline({state})`: the Orchestrator node wired to the five cards ("In parallel", then "Then, in order"), one expanded trace at a time and the pre-run line. |
| `frontend/components/pipeline/agent-card.tsx` | `AgentCard`: glyph, status word, summary, duration; `aria-expanded` trace directly beneath with numbered steps and a running indicator. |
| `frontend/components/pipeline/status-glyph.tsx` | `StatusGlyph`: idle circle, running dot, done check, error cross. Never a risk color. |
| `frontend/components/pipeline/reactive-measures.tsx` | `ReactiveMeasures({measures, level, trails})`: its own panel section after the agents, with the overall level's treatment and a summary line. Measures cluster by `MEASURE_TIMINGS` (now, within 1 h, 6 h, 24 h), soonest first; each card has the trail badge, its `MEASURE_CATEGORY_LABELS` label, the title, and the detail, and public items are marked "Draft, not sent". |
| `frontend/components/pipeline/analyze-button.tsx` | `AnalyzeButton({running, onAnalyze})`: **Analyze now**, "Analyzing…" and disabled while running. |
| `frontend/components/panel/hazard-block.tsx` | Step 23. Not rendered since the hill card rebuild; kept for later. `HazardBlock`: what it is, why it was flagged, confidence, how to avoid it, always in that order, with the level treatment and a close button. Says so when the hazard is a preview. |
| `frontend/components/panel/hiker-card.tsx` | Step 25. Not rendered since the hill card rebuild; kept for later. `HikerCard({state, onBack})`: replaces the ranger panel's content. Trail name, level word, the hiker sentence, the bypass name, and its added distance and climb from `GET /forecast`. Loading skeleton and error line. Never shows drivers, probability, or confidence. |
| `frontend/components/panel/level.tsx` | Step 23. `LevelWord` (dot and word in the level color), `NeedsReviewTag`, `LEVEL_TEXT`, `LEVEL_TREATMENT` (the High and Extreme border and tint). |
| `frontend/components/icons.tsx` | Step 23. Inline SVG line icons: circle, check, x, minus, warning triangle, chevron. |
| `frontend/lib/run-stream.ts` | Step 23. `followRun(runId, { onRun, onEvent, onLost })`: follows `WS /runs/{id}/stream` to the final `RunUpdate`; when the socket drops mid-run it asks `GET /runs/{id}` and reconnects up to twice before calling it lost. Returns a stop function. |
| `frontend/scripts/copy-maplibre-worker.mjs` | `postinstall`: copies MapLibre's worker modules to `frontend/public/maplibre/` (gitignored), where the map loads them. |

Routes: `/` (globe) and `/mountains/[slug]`. The mountain page reads the mountain and its layers from the API; its agent run is client-side and illustrative until `lib/run-stream.ts` is wired in as an `AgentSource`.

The map loads terrain tiles from `s3.amazonaws.com` in the browser, and Mapbox imagery from `api.mapbox.com` when a token is set.

## Backend (exists)

FastAPI on Python 3.11. Run from `backend/` with `uvicorn app.main:app --reload --port 8000`.

| File | What it is |
|---|---|
| `backend/requirements.txt` | FastAPI, Uvicorn, Pydantic, HTTPX, psycopg 3 with `psycopg-pool`, `python-dotenv`, `numpy`, `rasterio`, `pillow`, `mercantile` for tiles, `shapely` for the hazard zone and trail risk (step 18), and `networkx` for the bypass (step 19). |
| `backend/requirements-dev.txt` | `pytest`, for `python -m pytest` from `backend/`. |
| `backend/tests/test_contracts.py` | The seams other code builds against: the Model B input seam (`score()` normalises any float array and CRS to float32 and a string, and the `HourlyRain` it passes keeps every series aligned with its hours), each agent's output schema as Gemini and Grok actually receive it (no `$ref`, every object closed, `required` naming every property), and the JSON-nativeness of every tool result, agent payload, `AgentEvent`, `Run`, and `Advisory`. |
| `backend/tests/test_weather_series.py` | Gaps and alignment in the hourly series: an all-null series is absent rather than zero, a gap fills from the nearest reading, filling never changes the length, and `freeze_thaw_cycles` counts round trips rather than crossings. |
| `backend/tests/` | `conftest.py` (a `db_conn` fixture that skips without a database), `test_agent_schemas.py` (every output schema rejects a missing field, an extra field, and bad values; `llm_schema` is flat and closed), `test_router.py` (each routing rule, fallbacks, forced provider, resting), `test_providers.py` (request shapes and parsing for both providers against a mock transport, error classes, no key in errors), `test_tools.py` (each tool returns Rainier facts with no model call), `test_pipeline.py` (the five agents end to end through the fake APIs in-process: routing, fallback when Gemini is down, the Writer's repair round, a run without rain, no keys), `test_runs_api.py` (analyze, the stream, `GET /runs`, a failed run keeping the last hazard, reading a run after a restart, and the 404s and 409, against a scratch database it creates and drops), and `fake_llm.py`, a stand-in for the Gemini and xAI APIs for tests and offline work (`uvicorn tests.fake_llm:app --port 8090`; answers are built from the prompt's facts and named `fake-...`; `FAKE_LLM_DELAY_S`, `FAKE_LLM_FAIL`, `FAKE_LLM_BAD_WRITER`). |
| `backend/app/__init__.py` | Package marker. |
| `backend/app/main.py` | `app`. CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` for GET and POST. Plus any origins in `CORS_ORIGINS`. Mounts the mountains and runs routers and serves `backend/tiles/` at `/tiles`. A pool timeout or connection error returns 503 `{"detail": "Database unavailable"}`. `GET /health` returns `{"status": "ok"}` without touching the database. |
| `backend/app/config.py` | Loads the repo root `.env`. `database_url()` returns `DATABASE_URL` or raises with the fix. `cors_origins()` reads extra origins from `CORS_ORIGINS`. `REPO_ROOT`. |
| `backend/app/db.py` | `connect()` opens one psycopg connection for scripts. `get_pool()` makes the API's pool on first use, under a lock (dict rows, connections checked before use so hosted Postgres idling is safe, `POOL_TIMEOUT_S` = 5 s wait). `get_conn()` is the FastAPI dependency. `close_pool()` runs at shutdown. |
| `backend/app/schema.sql` | Six tables: `mountains`, `trails`, `trail_segments`, `analysis_runs`, `hazards`, `alerts`. UUID keys, geometry as `jsonb`, CHECK constraints for risk levels, run status, hazard type, and alert action. `hazards` also holds `trail_id`, `start_mile`, `end_mile` (step 18) and `bypass` jsonb (step 19), with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` lines that bring an older database up to date. Every statement is `IF NOT EXISTS`. |
| `backend/app/schema.py` | `python -m app.schema [--reset]`. `apply_schema(reset)` runs `schema.sql` and returns the tables present. `--reset` drops the six tables first. |
| `backend/app/seed.py` | `python -m app.seed`. `load_mountains(conn)` upserts `data/seed/mountains.json` by slug and removes static mountains the file no longer lists (children cascade; live mountains are never removed). The seed risk applies only while `last_analyzed_at` is null. `load_trails(conn)` upserts `data/seed/trails.geojson` by mountain and name, removes every trail the file no longer lists (for all mountains), and rejects a name repeated for one mountain. `load_trail_segments(conn)` upserts `data/seed/trail_segments.geojson` by trail and `seq`, keeps a segment's risk only while its line and miles are unchanged, and removes segments the file no longer lists. |
| `backend/app/mountain_catalog.py` | Offline only: `--write-seed --source overpass` (default) queries Overpass in 120 tiles (10 latitude bands × 12 longitude slices of 30°, elevation ≥ 1800 m filtered server-side, per-tile logs, mirror fallback with retries), then `pick_stratified` spaces candidates at least 1° apart (highest peak per neighborhood wins, so pins never stack), gives every occupied latitude band an even share of the ~1000 slots, and round-robins each band's quota across its longitude slices, so the Americas, Europe, and Asia all land pins. Raw rows are cached in `data/raw/overpass_peaks_raw.json` for reselection via `--source cache`. Refuses to overwrite the seed when fewer than 500 rows come back. Runtime: `ensure_catalog` / `sync_catalog` / `POST /mountains/catalog/sync` load that JSON into Postgres only—no Wikidata or Overpass on request. |
| `backend/app/models.py` | Pydantic response models: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard` (with `trail_id`, `trail_name`, `start_mile`, `end_mile` from step 18 and `bypass` from step 19), `Bypass`, `BypassPiece`, `MountainDetail.active_run_id` (step 22), `HistoricalEvent`, `LayerTiles`, plus `HazardType`, `Geometry`, and `RiskLevel` from `app/risk.py`. `frontend/lib/types.ts` mirrors them. |
| `backend/app/routes/mountains.py` | `GET /mountains`: every mountain, live first. `GET /mountains/{slug}`: the mountain, its trails with ordered segments, `active_hazard` (latest by `created_at`, with its trail's name, or null), `historical_events`, and `active_run_id` (a run going now, from the in-process registry). `GET /mountains/{slug}/layers/{layer}`: `LayerTiles` for a rendered layer in `LAYERS` (`susceptibility`, `probability`); 404 for static mountains, unknown layers, or layers not rendered yet (the detail says how to render it). 404 for an unknown slug. |
| `backend/app/history.py` | Step 14. `historical_events(slug)`: the catalog points in `data/seed/landslides.geojson` as `HistoricalEvent`s, for `mount-rainier` only. Re-read when the file changes. Empty while the file is missing. |
| `backend/app/ml/tiles.py` | Shared tiler, free of API imports so `ml/scripts/` can use it. `warp_tile` resamples a raster onto one 256 px EPSG:3857 tile. `palette_image` writes 8-bit PNGs on the stepped risk ramp from the design addendum (low transparent; moderate, high, extreme at 0.40, 0.55, 0.70 alpha), at zlib level 6 so a run renders 383 tiles in about 3 s. `render_xyz(raster, layer)` renders every tile over the bbox into `backend/tiles/<layer>/` via a temp folder swap and writes `metadata.json` with a `version` and the raster's `METHOD` tag. `read_metadata(layer)`. |
| `backend/app/risk.py` | Step 18. The shared risk vocabulary, free of API imports: `RiskLevel`, `RISK_LEVELS`, `BIN_EDGES` (0.2, 0.45, 0.7), `HIGH_THRESHOLD`, `RISK_HEX` (Design Language colors for the tiles), `risk_level(p)`, `level_index`, `level_spread`, `hex_rgb`. |
| `backend/app/weather.py` | `get_hourly_rain()`: hourly weather for the Rainier peak from Open-Meteo, downscaled to 1,650 m (Paradise), past 7 days and next 4, cached 5 minutes. Precipitation drives the model; temperature, snowfall, wind, soil moisture, and the freezing level (`EXTRA_SERIES`) are context the agents read. `_series()` keeps every series the same length as `times` so `now_index` still points at now, filling a gap forward from the last reading and backward from the first; a series with no readings at all (Open-Meteo returns soil moisture as all nulls at this elevation) comes back empty and reads as null rather than as a measured zero. With `OPEN_METEO_FIXTURE` set it loads that file instead, shifted so its `fixture_now` is the current hour, and says `source: "fixture"`. `HourlyRain.total`, `.window`, `.at_now`, `daily_totals_before_now`, `window_hours`, `as_of`, `freeze_thaw_cycles`, `try_hourly_rain()`, and `summarize()` to a `RainSummary`. |
| `backend/fixtures/open_meteo_storm.json` | A synthetic storm in Open-Meteo's response shape, for offline work only: 83 mm in the past 72 hours, 30 mm in the next 24. Marked synthetic in its `_note`. |
| `backend/app/ml/probability.py` | Step 18. The one seam to Model B. `score(rain)` calls `app.ml.model_b.run(rain)` when that module exists (reading `.probability`, `.transform`, `.crs`), and otherwise returns the susceptibility map with `method` `"susceptibility stand-in (Model B pending)"`. `ProbabilityMap` (`values`, `transform`, `crs`, `method`, `is_stand_in`), `summarize(values)` (cells, range, share per level), `write(map)` to `ml/artifacts/probability.tif` with a `METHOD` tag. |
| `backend/app/ml/hazard.py` | Step 18, free of API imports. `sample_max(map, coords)`: the worst cell along a line, sampled every 10 m. `segment_risks(map, segments)`: each hero segment's probability (the worst cell its tread crosses) and level. `flagged_run(risks)`: the worst segment grown along the trail while neighbors stay at high or above, as `FlaggedRun` (miles, seqs, peak, level); None when nothing reaches high. `hazard_zone(map, flagged_segments)`: the 8-connected high cells within `CORRIDOR_M` (250 m) of the flagged miles that touch them, as one simplified GeoJSON Polygon, with area, peak and mean probability, centroid, terrain stats under it from `data/processed/features.tif` (slope, facing, curvature, distance to channel, land cover, TWI, and box medians), a `type_hint` (debris flow when channelized), and `drivers_hint`. |
| `backend/app/assessment.py` | Steps 18 and 19. `python -m app.assessment [--save] [--slug]`. `hero_trail(conn)`, `assess(conn, slug, rain)` (the map, segment risk, flagged run, zone, bypass, and every trail's score as an `Assessment`, writing nothing), `publish(conn, a)` (probability tiles plus each segment's `risk_level` and `probability`), `save_hazard(conn, a, run_id=..., ...)` (a hazard row with its miles and bypass; a preview when `run_id` is null), `describe(a)` (plain what, why, and how-to-avoid lines from the facts), `signed_miles`, `signed_feet`, `overlap_check`, `level_runs`, `mile_text`. About 1 s to score, 3 s to publish. |
| `backend/app/bypass.py` | Step 19. `load_network()` reads `data/seed/trail_network.geojson` (cached, re-read when it changes). `find_bypass(flagged, map)`: for junctions within `SEARCH_MI` (3 mi) before and after the flagged miles, the off-loop detour with the least walking plus trail given up, where a meter at high or above counts `1 + HIGH_PENALTY` (4) times; detours that give up more than `MAX_SKIPPED_MI` (2 mi) of unflagged trail do not count. Returns a `Bypass` (name, via, leave and rejoin miles, length, replaced length, added km and climb walking the trail's way, worst level, line, and per-edge pieces with their own level), or None when no trail runs around the miles. |
| `backend/app/trailscan.py` | Every mapped trail on the mountain scored against the same probability map, so the advisory can name routes off the hero trail. `scan_trails(conn, slug, probability, hero_trail_id, zone_polygon)` returns a `TrailScore` per trail (max, mean, share at high or above, level, worst point, distance to the zone, whether it crosses it, US units). `most_exposed`, `safest` (degrades to least-bad rather than emptying), `relative_only`, `resolve` (a name a model wrote back to the catalog, tolerating case and a missing "Trail"), `summarize`. `MIN_RECOMMENDABLE_KM`, `SAFE_CEILING`. |
| `backend/app/agents/schemas.py` | What each agent returns (`TerrainReport`, `WeatherReport`, `TrailReport`, `HistoryReport`, `RouteScan`, `SynthesisReport`, `AlertDraft`, in `AGENT_OUTPUTS`): every field required, objects closed, each with 2 to 4 `reasoning` steps. `SynthesisReport` is the decision: severity, action, exactly three `AvoidRoute`s and three `SafeRoute`s, a `RangerResponse` (posture, priority, headline, channels, actions, staffing, timeline, escalate-if), and an analysis paragraph. The advisory the API returns: `Advisory` with `AdvisoryRoute`, `AdvisoryResponse`, `AdvisoryHazard`, `AdvisoryConditions`, `AdvisoryModel`, `AdvisoryAlert`, `AgentVerdict`. Stream shapes mirrored in `frontend/lib/types.ts`: `AgentEvent`, `AgentTrace`, `RouteDecision`, `RouteRule`, `ToolCall`, `Attempt`, `Usage`, `Run` (now carrying `advisory`), `RunUpdate`. `AGENT_ORDER`, `ANALYSTS`, `AGENT_LABELS`, `Driver`, `POSTURES`, `PRIORITIES`, `Channel`. |
| `backend/app/agents/advisory.py` | The guard rails on the Risk Synthesizer's answer. `route_problems(avoid, safe, scores)` rejects a trail that is not in the catalog, is not on the right shortlist, or is on both lists, phrased so the agent can fix it and try again. `clamp_response(response, severity, action, needs_review)` holds the posture to what the severity allows (`POSTURE_RANGE`), caps it at an advisory when the action is to monitor or the analysts disagree, matches the priority to the posture (`PRIORITY_RANGE`), drops a channel the posture may not use (`CHANNEL_FLOOR`), and forces trailhead signage on a warning; it returns every change as a check. `avoid_pool`/`safe_pool` (the shortlists, with `AVOID_FLOOR` so clear ground is never a route to avoid), `merge_route`, `fallback_routes`, `fallback_response`, `posture_rank`, `priority_rank`. |
| `backend/app/agents/tools.py` | `RunContext` (the run's assessment, rain, and clock). Tools that return precomputed facts, never a model call: `get_model_prediction` (the ML model's output as the run's source of truth, with what it saw, its blind spots, the model card from `ml/artifacts/metrics.json`, the map summary, the zone, and the network summary; every agent calls it first), `get_raster_summary` (map summary, method, the hazard zone with terrain and nearby junctions), `get_trail_segments` (risk by mile, flagged miles, the bypass or the turn-back advice), `get_trail_catalog` (every mapped trail scored, with the `most_exposed` and `clearest` shortlists the advisory must pick from), `get_weather` (rain totals in mm and inches, Guzzetti thresholds and ratios, plus the conditions the hazard model never saw: temperature, freeze-thaw cycles, snowfall, wind, soil moisture, freezing level; a warning for fixture rain), `get_historical_events` (catalog points within a radius). `call_tool` records each call as a `ToolCall`. `threshold_mm(hours)`. |
| `backend/app/agents/prompts.py` | `SYSTEM_PROMPTS` per agent: shared ground rules (the ML prediction is the source of truth, facts only, the bins, no waiting on another analyst) plus each agent's job, following the design addendum's copy rules. `REPAIR`, the re-ask after a failed check. |
| `backend/app/agents/providers.py` | Step 20. `GeminiProvider` (generateContent with `responseJsonSchema` and `thinkingConfig.includeThoughts`, thought summaries parsed from parts) and `GrokProvider` (Responses API with a strict `json_schema` format and reasoning summaries, or Chat Completions with `GROK_API=chat`), over httpx. `LLMRequest`, `LLMResult`, `ProviderError` (with `retryable`), `llm_schema(model)` (refs inlined, titles dropped, objects closed), `model_label`, `make_providers`. Keys and models from `.env`; errors never carry a key. |
| `backend/app/agents/router.py` | `Router.route(agent, Signals)` picks Gemini Flash or Grok and returns a `RouteDecision` with every rule it checked: tier (the five analysts to Gemini, so they can fan out; the Synthesizer and Writer to Grok), the task (a zone peak within 0.05 of a bin edge, rain within a third of the 72-hour threshold, a missing or risky bypass, an empty landslide catalog, or fewer than three trails clearing the safe ceiling escalates to Grok; analysts agreeing at moderate or below, or a routine monitor notice, moves to Gemini), the latency budget (past 42 s of 60, Grok moves to Gemini), and availability (a missing key, or two failures in two minutes rests a provider for a minute). `LLM_ROUTER` forces one provider. `record_failure`, `record_success`, `NoProviderError`. |
| `backend/app/agents/pipeline.py` | `python -m app.agents.pipeline [--fixture-rain]` runs the agents once and prints the advisory. `Pipeline(ctx, router, providers, emit).run()`: the five analysts (Terrain, Weather, Trail, History, Route Scout) fan out in one `asyncio.gather`, then the Risk Synthesizer reads all five, then the Alert Writer. Per agent: route, tools, one model call validated against the schema (two tries per provider: a retry after a temporary failure, or a repair round after a failed check; then the fallback provider). Emits an `AgentEvent` on start and on finish or failure, with the trace. Code sets the final confidence (`CONFIDENCE_WEIGHTS`: terrain 0.30, weather 0.25, trail 0.20, routes 0.15, history 0.10), `needs_review` (spread of 2 levels), and the Synthesizer's guard rails; the ranger title is `ranger_line()`; `writer_problems()` holds the copy checks, with plain templates when the model keeps failing them. `_advisory()` assembles the `Advisory`. Returns a `PipelineResult` with a `Final`. |
| `backend/app/runs.py` | Runs in the API process, keyed by `run_id`. `registry.start(slug, mountain)` starts one in the background (or returns the one running), which inserts its `analysis_runs` row, fetches rain once, scores the assessment, runs the pipeline while relaying each `AgentEvent`, then in one transaction renders the probability tiles, stores segment risk, saves the hazard with the agents' text, and sets the mountain's level and `last_analyzed_at`. A failed run writes none of that. The final `Run` view, advisory included, is stored on the row. `RunState.view()`, `subscribe`, `unsubscribe`, `load_run(run_id)`, `latest_advisory(slug)`, `STEP_NAMES`. |
| `backend/app/routes/forecast.py` | Step 25. `GET /forecast?mountain_id=&trail_id=` (`mountain_id` takes the id or the slug): the latest finished run's hazard as the hiker card's facts: level, the Alert Writer's hiker sentence, the trail and miles, and the bypass with its added distance and climb. 404 until a run has finished with a hazard. |
| `backend/app/routes/runs.py` | `POST /mountains/{slug}/analyze` (202 with `run_id`; 200 with the running run's id; 409 for a static marker; 404 unknown), `GET /runs/{run_id}` (memory, then the database; 404 unknown), `GET /runs/{run_id}/advisory` (the run's whole conclusion; 409 while it is still going or if it failed), `GET /mountains/{slug}/advisory` (the newest advisory, from memory or the last finished run's row; 404 until one exists), `WS /runs/{run_id}/stream` (a `RunUpdate` snapshot, then each `AgentEvent` and `RunUpdate`, closed after the final one; an unknown run gets `{kind: "error"}` and close code 4404). |

### API responses

`GET /mountains` returns `Mountain[]`. `GET /mountains/{slug}` returns `MountainDetail`. IDs are UUID strings, times are ISO 8601 with a timezone, geometry is a GeoJSON geometry object.

```
Mountain       { id, name, slug, lat, lon, elevation_m, region, current_risk_level, last_analyzed_at | null, is_live }
MountainDetail   Mountain + { trails: Trail[], active_hazard: Hazard | null, historical_events: HistoricalEvent[],
                 active_run_id | null }
Trail          { id, name, geom (LineString), length_km | null, elevation_gain_m | null, segments: TrailSegment[] }
TrailSegment   { id, seq, geom (LineString), start_mile, end_mile, risk_level | null, probability | null }
Hazard         { id, run_id | null, type (landslide | debris_flow), severity, probability, confidence | null,
                 geom (Polygon), drivers: string[], what | null, why | null, how_to_avoid | null, needs_review, created_at,
                 trail_id | null, trail_name | null, start_mile | null, end_mile | null, bypass: Bypass | null }
Bypass         { name, via: string[], leaves_at_mile, rejoins_at_mile, length_km, replaced_km, added_km,
                 added_elevation_m, max_probability, level, geom (LineString), pieces: { trail | null, probability, level, geom }[] }
HistoricalEvent { id, date | null, title | null, category | null, trigger | null, location_accuracy | null,
                 source_name | null, source_link | null, catalog, lon, lat }
LayerTiles     { layer, tiles ("{API}/tiles/<layer>/{z}/{x}/{y}.png?v=<version>"), bounds [w, s, e, n], minzoom, maxzoom,
                 method | null, updated_at }
Run            { id, mountain_slug, status (running | done | error), phase, message, started_at, finished_at | null,
                 elapsed_s | null, agents: { <agent>: AgentEvent }, hazard_id | null, severity | null, needs_review | null,
                 method | null, rain: { source, as_of, past_72h_mm, next_24h_mm } | null, error | null, failed_agent | null }
RunUpdate      { kind: "run", run: Run }   (stream messages are RunUpdates and AgentEvents)
AgentEvent     { run_id, agent, status, summary, payload, trace: AgentTrace | null }
```

## Data and ML (exists)

| File | What it is |
|---|---|
| `data/seed/mountains.json` | ~1000 OpenStreetMap peaks (named, elevation ≥ 1800 m) picked stratified across latitude bands and 30° longitude slices so every continent shows on the globe, plus `mount-rainier` (`is_live: true`). Regenerate from `backend/`: `python -m app.mountain_catalog --write-seed --source overpass`. Fields in `data/AGENTS.md`. |
| `data/seed/trails.geojson` | Step 14. 67 named Rainier trails from OpenStreetMap (via Overture Maps), 252 km, one feature per line, ODbL. The hero trail, `Skyline Trail`, is the NPS loop from the Paradise trailhead, clockwise: 8.87 km, 560 m of gain. Climbing routes, forest roads, and names under 200 m are left out. |
| `data/seed/trail_segments.geojson` | Step 14. The hero trail cut every 0.1 mile: 55 segments with `seq`, `start_mile`, `end_mile`, mile 0 at the Paradise trailhead. |
| `data/seed/trail_network.geojson` | Step 19. The walkable network the bypass routes on, `[lon, lat, elevation m]` vertices, ODbL. Format in `data/AGENTS.md`. |
| `data/AGENTS.md` | Seed formats and data rules. |
| `data/seed/sources.md` | URL, access date, licence, grid, and checks for each step 10 file. The landslide entry is pending, with the command that finishes it. |
| `data/raw/rainier_dem_cop30.tif` | Gitignored. Copernicus DEM GLO-30 clipped to the bbox, EPSG:4326, 1405 x 721 px. Rebuild with the step 10 script. |
| `data/raw/rainier_landcover_worldcover2021.tif` | Gitignored. ESA WorldCover 2021 class codes clipped to the bbox, EPSG:4326, 4680 x 2400 px. |
| `ml/requirements.txt` | Grouped by step: `rasterio`, `numpy` (below 2.4 for pysheds), `requests`, `scipy`, `pandas`, `pyarrow`, `pysheds`, `lightgbm`, `scikit-learn`, `mercantile`, `pillow`, `shapely`, `networkx`, `pyproj`. |
| `ml/scripts/build_features.py` | Step 11. `python ml/scripts/build_features.py [--landslides PATH]`. Builds a 30 m grid in UTM zone 10N (1004 x 757 cells) and writes `data/processed/features.tif` with seven bands: elevation, Horn slope, aspect (compass bearing, NaN on flats), Zevenbergen-Thorne curvature (negative = concave), distance to drainage (D8 channels at 0.2 km2, via pysheds), WorldCover land cover (mode resampled), and topographic wetness index. When landslide points exist it writes `data/processed/features.parquet`: positives within 50 m of `exact` or `1km` points, negatives 1:3 from ground over 500 m away, `label`, `region` (7.5 km blocks), `row`, `col`. |
| `data/processed/features.tif` | Gitignored. The step 11 feature stack. |
| `ml/scripts/train_susceptibility.py` | Step 12. `python ml/scripts/train_susceptibility.py [--table PATH] [--artifacts DIR]`. With the labeled table: LightGBM, held-out spatial regions (at least 20% of positives), AUC and precision at 0.45, gain importance, refit on all rows, full-map prediction. Without it: a knowledge-driven index (weights in `INDEX_WEIGHTS`, stretched between the 2nd and 98th percentile of the box) and `trained: false`. |
| `ml/artifacts/metrics.json` | Method, `trained`, AUC, precision at the high threshold, map summary. Committed so the current status is visible. |
| `ml/artifacts/feature_importance.json` | Gain importance (LightGBM) or the index weights. |
| `ml/artifacts/susceptibility.tif` | Gitignored. 0-1 susceptibility on the 30 m UTM grid. Input to tiles (step 13), Model B (step 17), and the probability stand-in until Model B lands (step 18). |
| `ml/artifacts/probability.tif` | Gitignored. The latest 72-hour probability map on the same grid, written by `app/ml/probability.py` before the probability tiles render. |
| `ml/artifacts/susceptibility_lgbm.txt` | The trained model, written only when labels exist. |
| `ml/scripts/render_tiles.py` | Steps 13 and 18. `python ml/scripts/render_tiles.py [--layer NAME] [--raster PATH] [--zooms 10-14]`. Thin CLI over `backend/app/ml/tiles.py`. Susceptibility: 383 tiles, z10-z14, about 3.5 s. |
| `backend/tiles/` | Gitignored. Rendered layers, one folder each, with `metadata.json`: `susceptibility` (step 13) and `probability` (step 18, re-rendered by each run). |
| `ml/scripts/import_trails.py` | Step 14. `python ml/scripts/import_trails.py [--force] [--segments PATH] [--out PATH] [--dem PATH] [--hero-segments PATH]`. Reads walkable OpenStreetMap segments in the bbox from the Overture Maps transportation GeoParquet on S3 (release `OVERTURE_RELEASE`, only the row groups whose bbox statistics overlap, about 300 MB), caches them in `data/raw/rainier_trail_segments.geojson`, merges them by name through a walkable graph, measures length and gain on the DEM, and writes `data/seed/trails.geojson`. Joins the Skyline and Upper Skyline Trails into the hero loop and writes its 0.1-mile segments to `data/seed/trail_segments.geojson`. |
| `ml/scripts/build_trail_network.py` | Step 19. `python ml/scripts/build_trail_network.py [--segments PATH] [--dem PATH] [--out PATH]`. From step 14's segment cache and the DEM, writes `data/seed/trail_network.geojson`: the Skyline loop re-cut at its 24 junctions from the same simplified line as the mile segments (each piece with `from_mile` and `to_mile`), plus the 114 walkable edges within 2.5 km of it that connect to it, junctions snapped onto the loop, with DEM elevations every 30 m. 103 kB, about 1 s. |
| `data/raw/rainier_trail_segments.geojson` | Gitignored. Every walkable segment in the bbox (517), clipped, with OSM ids: the network step 19 routes on. |
| `ml/scripts/download_sources.py` | Step 10. `python ml/scripts/download_sources.py [--only dem,landcover,landslides] [--force] [--glc-csv URL_OR_PATH]`. Reads the bbox window of the Copernicus DEM and ESA WorldCover COGs over HTTP ranges, writes `data/raw/`, and prints a check that each file covers the bbox. Filters the NASA Global Landslide Catalog CSV to the bbox into `data/seed/landslides.geojson`. A failed stage does not stop the others. |

## Planned layout

Create these as the steps call for them. Paths match [`../implementation-steps.md`](../implementation-steps.md).

`AgentEvent` shape, fixed in step 7 (`frontend/lib/types.ts`):

```json
{ "run_id": "", "agent": "terrain|weather|trail|synthesizer|writer", "status": "waiting|running|done|error", "summary": "", "payload": {} }
```

### Backend

| Path | Step | Role |
|---|---|---|
| `backend/app/ml/model_b.py` | 17 | Susceptibility plus Open-Meteo rain |
| `backend/app/ml/pressure.py` | 26 | Up to five ranked pressure points from the probability map |
| `backend/app/ml/runout.py` | 27 | Runout frames and steps from one pressure point, no model call |
| `backend/app/simulations.py` | 28 | In-process simulations keyed by id, and the callouts call through the router |
| `backend/app/routes/simulations.py` | 26, 28 | `GET /mountains/{slug}/pressure-points`, `POST /mountains/{slug}/simulate`, `GET /simulations/{id}`, `WS /simulations/{id}/stream` |

API the frontend should call, from the spec. All of it exists except the step 26 and 28 routes above:

```
GET  /health
GET  /mountains
GET  /mountains/{slug}
GET  /mountains/{slug}/layers/{layer}   (step 13: susceptibility, step 18: probability)
POST /mountains/{slug}/analyze          → { run_id }   (step 22)
GET  /runs/{run_id}                                     (step 22)
WS   /runs/{run_id}/stream                              (step 22)
GET  /forecast?mountain_id&trail_id                     (step 25)
```

`POST /analyze` is rejected with 409 when `is_live` is false.

### Frontend

| Path | Step | Role |
|---|---|---|
| `frontend/components/mountain-panel/` | 29, 30 | The centered panel over the globe: panel map, pressure point list, simulation column, callouts |
| `frontend/lib/simulation-stream.ts` | 30 | Follows `WS /simulations/{id}/stream` |

### Data and ML

| Path | Step | Role |
|---|---|---|
| `data/seed/landslides.geojson` | 10, 14 | Pin source. Pending: `download_sources.py --only landslides` needs data.nasa.gov |

## Invariants

- Risk levels are `low`, `moderate`, `high`, `extreme`.
- Bins: low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7.
- Rainier bbox: west -121.93, south 46.76, east -121.54, north 46.96.
- Tiles are Web Mercator XYZ. A tile that is offset from the ridges is a broken step 13 or 18, not a map setting to tweak later.
- Agents return Pydantic-validated JSON. Tools return precomputed facts. They do not scan the raster and they do not invent trail geometry.
