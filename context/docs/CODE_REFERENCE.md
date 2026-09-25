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
| `frontend/app/mountains/[slug]/page.tsx` | Mountain page, server-rendered from `GET /mountains/{slug}` and, for live mountains, `GET /mountains/{slug}/layers/probability` and `.../susceptibility` (a failed layer leaves the map without it). While the probability layer is the susceptibility stand-in, the panel says so in one muted line: the terrain map (about 70% of the width, keyed by slug) and the ranger panel with name, region, elevation, summit, overall risk, last refresh, one sentence (the Synthesizer's summary replaces it in step 23), and the trail list: the hero trail with its miles and segments, then the other trails behind a disclosure. **Analyze now** renders only when `is_live` (disabled until step 23). Static mountains show a fixed-risk note. Fades in. |
| `frontend/app/mountains/[slug]/loading.tsx` | Plain dark screen while the page loads. Lets the globe prefetch the route. |
| `frontend/app/mountains/[slug]/error.tsx` | API failure: message, **Try again** (`retry()` refetches), link back to the globe. |
| `frontend/app/mountains/[slug]/not-found.tsx` | Unknown slug. |
| `frontend/app/not-found.tsx` | Site-wide dark 404. |
| `frontend/app/globals.css` | Basalt and glacier tokens with the shadcn role names from the design addendum (`--background`, `--muted`, `--card`, `--popover`, `--secondary`, `--foreground`, `--muted-foreground`, `--primary`, `--ring`, `--border`, `--input`, `--accent`, `--destructive`), mapped to Tailwind colors, plus `risk-low`, `risk-moderate`, `risk-high`, `risk-extreme`. Font tokens `sans` and `mono`. `animate-fade-in` and the `bg-grid` utility. `.terra-popup` puts MapLibre popups on the panel surface. Dark base styles. |
| `frontend/app/icon.tsx` | Favicon, generated with `ImageResponse` from `THEME` colors. |
| `frontend/lib/theme.ts` | `THEME` (neutral and accent hex values by role) and `RISK_COLORS` (keyed by `RiskLevel`) for WebGL, Mapbox, and the app icon. Mirrors `globals.css`. |
| `frontend/lib/types.ts` | Mirrors `backend/app/models.py`: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard` (with `trail_id`, `trail_name`, `start_mile`, `end_mile`, `bypass`), `Bypass`, `BypassPiece`, `HistoricalEvent`, `RiskLevel` (with `RISK_LEVELS`), `HazardType`, `LineString`, `Polygon`, `Position`, `LayerTiles`. Stream types: `AgentEvent` (with an optional `trace`), `AgentName` (`AGENT_NAMES`), `AgentStatus` (`AGENT_STATUSES`), and for the reasoning panel `AgentTrace`, `RouteDecision`, `RouteRule`, `ToolCall`, `Attempt`, `Usage`, `ProviderName` (`PROVIDER_NAMES`), and for step 22 `Run`, `RunUpdate`, `RunStatus` (`RUN_STATUSES`), `RunPhase`, `RainTotals`, and `MountainDetail.active_run_id`. |
| `frontend/lib/api.ts` | `API_URL` from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). `getMountains(init?)`, `getMountain(slug, init?)` (null on 404), `getLayer(slug, layer, init?)` (null on 404), `startAnalysis(slug)` (the run id; an error carries the API's `detail`), `getRun(runId)` (null on 404), `runStreamUrl(runId)`, `ApiError` with `status`. Requests use `cache: "no-store"`. |
| `frontend/lib/agent-events.ts` | `isAgentEvent(value)` and `parseAgentEvents(value)`: runtime checks for JSON that claims to be `AgentEvent`s, including the parts of a `trace` the reasoning panel reads. `isRunUpdate(value)` for the stream's run messages. |
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
| `frontend/lib/format.ts` | `riskLabel`, `formatUtc` ("Sep 25, 10:50 UTC"), `refreshLabel` (last analysis, "Not analyzed yet", or "Static marker, fixed risk"), `formatElevation`, `formatMiles` (km to "5.5 mi"), `formatLatLon` ("46.8523° N, 121.7603° W"), `formatDate` ("2011-05-01" to "May 1, 2011"), `humanize` ("debris_flow" to "Debris flow"). |
| `frontend/public/globe/` | `earth-day.jpg` (4096×2048 color) and `earth-topology.png` (2048×1024 bump map). |
| `frontend/next.config.ts` | Loads the repo root `.env` with `process.loadEnvFile` so the app and the API share one file. Variables already set win. |
| `frontend/postcss.config.mjs` | Tailwind PostCSS plugin. |
| `frontend/tsconfig.json` | Strict TypeScript. Path alias `@/*` → repo root of `frontend/`. |
| `frontend/eslint.config.mjs` | `eslint-config-next`. Ignores the copied worker in `public/maplibre/`. |
| `frontend/components/map/mountain-map.tsx` | `MountainMap`: loads the terrain map with `ssr: false`, showing the surface color meanwhile. |
| `frontend/components/map/terrain-map.tsx` | `TerrainMap({ name, lon, lat, elevationM, trails, isLive, probability, susceptibility, hazard, historicalEvents })`: the MapLibre map. 3D terrain, navigation and scale controls, a summit label on the terrain, and the trails from `GET /mountains/{slug}`, the hero trail colored by segment risk. Opens framed on the summit and the hero trail (or on the summit alone), pitched 55°. On live mountains: the 72-hour heat map as the default layer (step 18), fading in over 600 ms once its tiles load and again when its tiles change (instant under reduced motion; draped textures are redrawn each frame because MapLibre's terrain cache ignores paint changes); the hazard zone's 2 px outline in its level color; the susceptibility raster, which hides the heat map while on (step 16, no fade); past landslide pins with a popup per pin (date, type, source; catalog text goes in as text, only http(s) links become links). Shows "Loading terrain…" until the map loads, and a message when WebGL is off or the map fails. |
| `frontend/components/map/map-style.ts` | The style: AWS Terrain Tiles (Terrarium) for terrain, an elevation tint (`color-relief`, gray valleys to white summit) and hillshade for the light relief, or Mapbox satellite when `NEXT_PUBLIC_MAPBOX_TOKEN` is set. Trail layers: other trails thin and dashed, the hero trail's segments cased and colored by `risk_level` (ink while unscored). Exports `CAMERA`, `MAP_COLORS`, `SOURCE`, `LAYER`, `TERRAIN_EXAGGERATION`, `mountainStyle`, `trailFeatures`, `openingBounds`, `isHero`, for step 16 `rasterSource` (a `LayerTiles` as a raster source), `historyFeatures`, and `HISTORY_LAYER` (8 px pins in the text color with a dark ring, never a risk color), and for step 18 `HEAT_FADE_MS`, `hazardFeatures`, and `HAZARD_OUTLINE_COLOR`. |
| `frontend/components/map/layer-toggles.tsx` | `LayerToggles({ toggles, onToggle })`: the toggle group over the lower left of the map (step 16). Each toggle is a pressed/unpressed button; `unavailable` disables it and says why in its title. Hidden on static mountains. |
| `frontend/scripts/copy-maplibre-worker.mjs` | `postinstall`: copies MapLibre's worker modules to `frontend/public/maplibre/` (gitignored), where the map loads them. |

Routes: `/` (globe) and `/mountains/[slug]`.

The map loads terrain tiles from `s3.amazonaws.com` in the browser, and Mapbox imagery from `api.mapbox.com` when a token is set.

## Backend (exists)

FastAPI on Python 3.11. Run from `backend/` with `uvicorn app.main:app --reload --port 8000`.

| File | What it is |
|---|---|
| `backend/requirements.txt` | FastAPI, Uvicorn, Pydantic, HTTPX, psycopg 3 with `psycopg-pool`, `python-dotenv`, `numpy`, `rasterio`, `pillow`, `mercantile` for tiles, `shapely` for the hazard zone and trail risk (step 18), and `networkx` for the bypass (step 19). |
| `backend/requirements-dev.txt` | `pytest`, for `python -m pytest` from `backend/`. |
| `backend/tests/` | `conftest.py` (a `db_conn` fixture that skips without a database), `test_agent_schemas.py` (every output schema rejects a missing field, an extra field, and bad values; `llm_schema` is flat and closed), `test_router.py` (each routing rule, fallbacks, forced provider, resting), `test_providers.py` (request shapes and parsing for both providers against a mock transport, error classes, no key in errors), `test_tools.py` (each tool returns Rainier facts with no model call), `test_pipeline.py` (the five agents end to end through the fake APIs in-process: routing, fallback when Gemini is down, the Writer's repair round, a run without rain, no keys), `test_runs_api.py` (analyze, the stream, `GET /runs`, a failed run keeping the last hazard, reading a run after a restart, and the 404s and 409, against a scratch database it creates and drops), and `fake_llm.py`, a stand-in for the Gemini and xAI APIs for tests and offline work (`uvicorn tests.fake_llm:app --port 8090`; answers are built from the prompt's facts and named `fake-...`; `FAKE_LLM_DELAY_S`, `FAKE_LLM_FAIL`, `FAKE_LLM_BAD_WRITER`). |
| `backend/app/__init__.py` | Package marker. |
| `backend/app/main.py` | `app`. CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` for GET and POST. Plus any origins in `CORS_ORIGINS`. Mounts the mountains and runs routers and serves `backend/tiles/` at `/tiles`. A pool timeout or connection error returns 503 `{"detail": "Database unavailable"}`. `GET /health` returns `{"status": "ok"}` without touching the database. |
| `backend/app/config.py` | Loads the repo root `.env`. `database_url()` returns `DATABASE_URL` or raises with the fix. `cors_origins()` reads extra origins from `CORS_ORIGINS`. `REPO_ROOT`. |
| `backend/app/db.py` | `connect()` opens one psycopg connection for scripts. `get_pool()` makes the API's pool on first use, under a lock (dict rows, connections checked before use so hosted Postgres idling is safe, `POOL_TIMEOUT_S` = 5 s wait). `get_conn()` is the FastAPI dependency. `close_pool()` runs at shutdown. |
| `backend/app/schema.sql` | Six tables: `mountains`, `trails`, `trail_segments`, `analysis_runs`, `hazards`, `alerts`. UUID keys, geometry as `jsonb`, CHECK constraints for risk levels, run status, hazard type, and alert action. `hazards` also holds `trail_id`, `start_mile`, `end_mile` (step 18) and `bypass` jsonb (step 19), with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` lines that bring an older database up to date. Every statement is `IF NOT EXISTS`. |
| `backend/app/schema.py` | `python -m app.schema [--reset]`. `apply_schema(reset)` runs `schema.sql` and returns the tables present. `--reset` drops the six tables first. |
| `backend/app/seed.py` | `python -m app.seed`. `load_mountains(conn)` upserts `data/seed/mountains.json` by slug. The seed risk applies only while `last_analyzed_at` is null. `load_trails(conn)` upserts `data/seed/trails.geojson` by mountain and name, removes every trail the file no longer lists (for all mountains), and rejects a name repeated for one mountain. `load_trail_segments(conn)` upserts `data/seed/trail_segments.geojson` by trail and `seq`, keeps a segment's risk only while its line and miles are unchanged, and removes segments the file no longer lists. |
| `backend/app/models.py` | Pydantic response models: `Mountain`, `MountainDetail`, `Trail`, `TrailSegment`, `Hazard` (with `trail_id`, `trail_name`, `start_mile`, `end_mile` from step 18 and `bypass` from step 19), `Bypass`, `BypassPiece`, `MountainDetail.active_run_id` (step 22), `HistoricalEvent`, `LayerTiles`, plus `HazardType`, `Geometry`, and `RiskLevel` from `app/risk.py`. `frontend/lib/types.ts` mirrors them. |
| `backend/app/routes/mountains.py` | `GET /mountains`: every mountain, live first. `GET /mountains/{slug}`: the mountain, its trails with ordered segments, `active_hazard` (latest by `created_at`, with its trail's name, or null), `historical_events`, and `active_run_id` (a run going now, from the in-process registry). `GET /mountains/{slug}/layers/{layer}`: `LayerTiles` for a rendered layer in `LAYERS` (`susceptibility`, `probability`); 404 for static mountains, unknown layers, or layers not rendered yet (the detail says how to render it). 404 for an unknown slug. |
| `backend/app/history.py` | Step 14. `historical_events(slug)`: the catalog points in `data/seed/landslides.geojson` as `HistoricalEvent`s, for `mount-rainier` only. Re-read when the file changes. Empty while the file is missing. |
| `backend/app/ml/tiles.py` | Shared tiler, free of API imports so `ml/scripts/` can use it. `warp_tile` resamples a raster onto one 256 px EPSG:3857 tile. `palette_image` writes 8-bit PNGs on the stepped risk ramp from the design addendum (low transparent; moderate, high, extreme at 0.40, 0.55, 0.70 alpha), at zlib level 6 so a run renders 383 tiles in about 3 s. `render_xyz(raster, layer)` renders every tile over the bbox into `backend/tiles/<layer>/` via a temp folder swap and writes `metadata.json` with a `version` and the raster's `METHOD` tag. `read_metadata(layer)`. |
| `backend/app/risk.py` | Step 18. The shared risk vocabulary, free of API imports: `RiskLevel`, `RISK_LEVELS`, `BIN_EDGES` (0.2, 0.45, 0.7), `HIGH_THRESHOLD`, `RISK_HEX` (Design Language colors for tiles and the Discord embed), `risk_level(p)`, `level_index`, `level_spread`, `hex_rgb`. |
| `backend/app/weather.py` | Step 18 (first written for step 17 and restored when step 17 was pulled). `get_hourly_rain()`: hourly precipitation for the Rainier peak from Open-Meteo, downscaled to 1,650 m (Paradise), past 7 days and next 4, cached 5 minutes. With `OPEN_METEO_FIXTURE` set (relative to the repo root) it loads that file instead, shifted so its `fixture_now` is the current hour, and says `source: "fixture"`. `HourlyRain.total(start_hour, end_hour)`, `daily_totals_before_now`, `window_hours`, `as_of`, `try_hourly_rain()` (the rain, or None and why), and `summarize()` to a `RainSummary` (past 24 h, 72 h, 7 days; next 24 h, 72 h; the wettest hour ahead). |
| `backend/fixtures/open_meteo_storm.json` | A synthetic storm in Open-Meteo's response shape, for offline work only: 83 mm in the past 72 hours, 30 mm in the next 24. Marked synthetic in its `_note`. |
| `backend/app/ml/probability.py` | Step 18. The one seam to Model B. `score(rain)` calls `app.ml.model_b.run(rain)` when that module exists (reading `.probability`, `.transform`, `.crs`), and otherwise returns the susceptibility map with `method` `"susceptibility stand-in (Model B pending)"`. `ProbabilityMap` (`values`, `transform`, `crs`, `method`, `is_stand_in`), `summarize(values)` (cells, range, share per level), `write(map)` to `ml/artifacts/probability.tif` with a `METHOD` tag. |
| `backend/app/ml/hazard.py` | Step 18, free of API imports. `sample_max(map, coords)`: the worst cell along a line, sampled every 10 m. `segment_risks(map, segments)`: each hero segment's probability (the worst cell its tread crosses) and level. `flagged_run(risks)`: the worst segment grown along the trail while neighbors stay at high or above, as `FlaggedRun` (miles, seqs, peak, level); None when nothing reaches high. `hazard_zone(map, flagged_segments)`: the 8-connected high cells within `CORRIDOR_M` (250 m) of the flagged miles that touch them, as one simplified GeoJSON Polygon, with area, peak and mean probability, centroid, terrain stats under it from `data/processed/features.tif` (slope, facing, curvature, distance to channel, land cover, TWI, and box medians), a `type_hint` (debris flow when channelized), and `drivers_hint`. |
| `backend/app/assessment.py` | Steps 18 and 19. `python -m app.assessment [--save] [--slug]`. `hero_trail(conn)`, `assess(conn, slug, rain)` (the map, segment risk, flagged run, zone, and bypass as an `Assessment`, writing nothing), `publish(conn, a)` (probability tiles plus each segment's `risk_level` and `probability`), `save_hazard(conn, a, run_id=..., ...)` (a hazard row with its miles and bypass; a preview when `run_id` is null), `describe(a)` (plain what, why, and how-to-avoid lines from the facts; how-to-avoid names the bypass or says to turn back), `signed_miles`, `signed_feet`, `overlap_check` (meters between the bypass and the flagged miles), `level_runs`, `mile_text`. About 0.4 s to score, 3 s to publish. |
| `backend/app/bypass.py` | Step 19. `load_network()` reads `data/seed/trail_network.geojson` (cached, re-read when it changes). `find_bypass(flagged, map)`: for junctions within `SEARCH_MI` (3 mi) before and after the flagged miles, the off-loop detour with the least walking plus trail given up, where a meter at high or above counts `1 + HIGH_PENALTY` (4) times; detours that give up more than `MAX_SKIPPED_MI` (2 mi) of unflagged trail do not count. Returns a `Bypass` (name, via, leave and rejoin miles, length, replaced length, added km and climb walking the trail's way, worst level, line, and per-edge pieces with their own level), or None when no trail runs around the miles. |
| `backend/app/agents/schemas.py` | Step 20. What each agent returns (`TerrainReport`, `WeatherReport`, `TrailReport`, `SynthesisReport`, `AlertDraft`, in `AGENT_OUTPUTS`): every field required, objects closed, each with 2 to 4 `reasoning` steps. Facts the code knows are never asked of a model. Stream shapes mirrored in `frontend/lib/types.ts`: `AgentEvent` (with an optional `trace`), `AgentTrace` (route, tools, attempts, thoughts, reasoning, checks, output, usage, timing), `RouteDecision`, `RouteRule`, `ToolCall`, `Attempt`, `Usage`, and for step 22 `Run` (status, phase, status line, timing, the latest event per agent, hazard id, severity, `needs_review`, method, `RainTotals`, error, failed agent) and `RunUpdate` (`{kind: "run", run}`). `AGENT_ORDER`, `AGENT_LABELS`, `Driver`. |
| `backend/app/agents/tools.py` | Step 20. `RunContext` (the run's assessment, rain, and clock). Tools that return precomputed facts, never a model call: `get_raster_summary` (map summary, method, the hazard zone with terrain and nearby junctions), `get_trail_segments` (risk by mile, flagged miles, the bypass or the turn-back advice), `get_weather` (rain totals in mm and inches, Guzzetti thresholds and ratios, a warning for fixture rain), `get_historical_events` (catalog points within a radius). `call_tool` records each call as a `ToolCall`. `threshold_mm(hours)`. |
| `backend/app/agents/prompts.py` | Step 20. `SYSTEM_PROMPTS` per agent: shared ground rules (facts only, the bins, plain text) plus each agent's job, following the design addendum's copy rules. `REPAIR`, the re-ask after a failed check. |
| `backend/app/agents/providers.py` | Step 20. `GeminiProvider` (generateContent with `responseJsonSchema` and `thinkingConfig.includeThoughts`, thought summaries parsed from parts) and `GrokProvider` (Responses API with a strict `json_schema` format and reasoning summaries, or Chat Completions with `GROK_API=chat`), over httpx. `LLMRequest`, `LLMResult`, `ProviderError` (with `retryable`), `llm_schema(model)` (refs inlined, titles dropped, objects closed), `model_label`, `make_providers`. Keys and models from `.env`; errors never carry a key. |
| `backend/app/agents/router.py` | Step 20. `Router.route(agent, Signals)` picks Gemini Flash or Grok and returns a `RouteDecision` with every rule it checked: tier (fast tasks to Gemini, strong to Grok), the task (a zone peak within 0.05 of a bin edge, rain within a third of the 72-hour threshold, or a missing or risky bypass escalates to Grok; three reports agreeing at moderate or below, or a routine monitor notice, moves to Gemini), the latency budget (past 42 s of 60, Grok moves to Gemini), and availability (a missing key, or two failures in two minutes rests a provider for a minute). `LLM_ROUTER` forces one provider. `record_failure`, `record_success`, `NoProviderError`. |
| `backend/app/agents/pipeline.py` | Step 21. `python -m app.agents.pipeline [--fixture-rain]` runs the five agents once and prints each payload, the final severity, and both texts. `Pipeline(ctx, router, providers, emit).run()`: Terrain and Weather together, then Trail, Synthesizer, Writer. Per agent: route, tools, one model call validated against the schema (two tries per provider: a retry after a temporary failure, or a repair round after a failed check; then the fallback provider). Emits an `AgentEvent` on start and on finish or failure, with the trace. Code sets the final confidence (`CONFIDENCE_WEIGHTS` 0.40, 0.35, 0.25), `needs_review` (spread of 2 levels), and the Synthesizer's guard rails; the ranger title is `ranger_line()`; `writer_problems()` holds the copy checks, with plain templates when the model keeps failing them. Returns a `PipelineResult` with a `Final`. |
| `backend/app/runs.py` | Step 22. Runs in the API process, keyed by `run_id`. `registry.start(slug, mountain)` starts one in the background (or returns the one running), which inserts its `analysis_runs` row, fetches rain once, scores the assessment, runs the pipeline while relaying each `AgentEvent`, then in one transaction renders the probability tiles, stores segment risk, saves the hazard with the agents' text, and sets the mountain's level and `last_analyzed_at`. A failed run writes none of that. The final `Run` view is stored on the row. `RunState.view()`, `subscribe`, `unsubscribe`, `load_run(run_id)` (a finished run from the database), `STEP_NAMES`. |
| `backend/app/routes/runs.py` | Step 22. `POST /mountains/{slug}/analyze` (202 with `run_id`; 200 with the running run's id; 409 for a static marker; 404 unknown), `GET /runs/{run_id}` (memory, then the database; 404 unknown), `WS /runs/{run_id}/stream` (a `RunUpdate` snapshot, then each `AgentEvent` and `RunUpdate`, closed after the final one; an unknown run gets `{kind: "error"}` and close code 4404). |

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
| `data/seed/mountains.json` | Mount Rainier (`is_live: true`, placeholder risk `moderate`), Huascarán (`high`), Mount Fuji (`low`). Fields in `data/AGENTS.md`. |
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

### Frontend

| Path | Step | Role |
|---|---|---|
| `frontend/components/panel/` | 23, 25 | Side panel, agent rows, hazard detail, hiker card |

`AgentEvent` shape, fixed in step 7 (`frontend/lib/types.ts`):

```json
{ "run_id": "", "agent": "terrain|weather|trail|synthesizer|writer", "status": "waiting|running|done|error", "summary": "", "payload": {} }
```

### Backend

| Path | Step | Role |
|---|---|---|
| `backend/app/ml/model_b.py` | 17 | Susceptibility plus Open-Meteo rain |
| `backend/app/alerts/discord.py` | 24 | Webhook post |

API the frontend should call, from the spec. Everything but `/forecast` exists:

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
