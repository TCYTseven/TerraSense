# Code reference

Map of the TerraSense repo. Update the matching section in the same change that adds, renames, or deletes a file.

Planned paths are labeled **planned**. They are not in the tree yet. Do not import them. When you create one, remove the planned label and document the real exports.

The product contract is [`../TerraSense.md`](../TerraSense.md). The build order is [`../implementation-steps.md`](../implementation-steps.md).

## What is in the tree

```
frontend/          Next.js app. Runs with npm run dev.
backend/           FastAPI service. Only the agent guide until step 3.
ml/scripts/        Offline scripts. Empty until step 10.
ml/artifacts/      Model outputs. Empty until step 12.
data/seed/         Committed seed files. Empty until step 5.
context/           Spec and the 25 implementation steps.
context/docs/      Team brief, handoff, UX, this file.
.claude/agents/    Subagent definitions: one builder per track and a reviewer.
AGENTS.md          Agent guide: folder owners, team rules, shared facts.
README.md          Pitch, the three commands, folder owners.
.env.example       Every environment variable, with a comment.
.gitignore         Ignores .env, data/raw/, data/processed/, ml/artifacts/*.tif, virtualenvs.
```

`ml/scripts/`, `ml/artifacts/`, and `data/seed/` hold a `.gitkeep` until their first real file lands.

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
| `frontend/package.json` | Scripts: `dev`, `build`, `start`, `lint`. Dependencies: Next, React, React DOM, `three`, `@react-three/fiber`, `@react-three/drei`. |
| `frontend/app/layout.tsx` | Root layout, full height. Loads Geist (UI) and Geist Mono (numbers) as CSS variables. Sets metadata and a dark `viewport`. |
| `frontend/app/page.tsx` | Home: the full-screen globe with the TerraSense name at the top left. |
| `frontend/app/globals.css` | Dark dispatch tokens as Tailwind colors: `background`, `surface`, `panel`, `line`, `foreground`, `muted`, `accent`, and `risk-low`, `risk-moderate`, `risk-high`, `risk-extreme`. Font tokens `sans` and `mono`. Dark base styles. |
| `frontend/app/icon.svg` | Favicon. |
| `frontend/lib/theme.ts` | `THEME` and `RISK_COLORS`: the same palette for WebGL code. Mirrors `globals.css`. |
| `frontend/components/globe/globe-view.tsx` | Client wrapper that loads the globe with `ssr: false`. |
| `frontend/components/globe/spinning-globe.tsx` | React Three Fiber canvas: textured Earth, atmosphere rim, idle spin, drag and zoom. |
| `frontend/public/globe/` | `earth-day.jpg` (4096×2048 color) and `earth-topology.png` (2048×1024 bump map). |
| `frontend/next.config.ts` | Default Next config. |
| `frontend/postcss.config.mjs` | Tailwind PostCSS plugin. |
| `frontend/tsconfig.json` | Strict TypeScript. Path alias `@/*` → repo root of `frontend/`. |
| `frontend/eslint.config.mjs` | `eslint-config-next`. |

Routes: `/` only.

## Backend (exists)

FastAPI on Python 3.11. Run from `backend/` with `uvicorn app.main:app --reload --port 8000`.

| File | What it is |
|---|---|
| `backend/requirements.txt` | FastAPI, Uvicorn, Pydantic, HTTPX, psycopg 3 with `psycopg-pool`, `python-dotenv`. Compatible-release pins. |
| `backend/app/__init__.py` | Package marker. |
| `backend/app/main.py` | `app`. CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` for GET and POST. `GET /health` returns `{"status": "ok"}`. |
| `backend/app/config.py` | Loads the repo root `.env`. `database_url()` returns `DATABASE_URL` or raises with the fix. `REPO_ROOT`. |
| `backend/app/db.py` | `connect()` opens one psycopg connection to `DATABASE_URL`. |
| `backend/app/schema.sql` | Six tables: `mountains`, `trails`, `trail_segments`, `analysis_runs`, `hazards`, `alerts`. UUID keys, geometry as `jsonb`, CHECK constraints for risk levels, run status, hazard type, and alert action. Every statement is `IF NOT EXISTS`. |
| `backend/app/schema.py` | `python -m app.schema [--reset]`. `apply_schema(reset)` runs `schema.sql` and returns the tables present. `--reset` drops the six tables first. |

## Planned layout

Create these as the steps call for them. Paths match [`../implementation-steps.md`](../implementation-steps.md).

### Frontend

| Path | Step | Role |
|---|---|---|
| `frontend/lib/types.ts` | 7 | `Mountain`, `Trail`, `TrailSegment`, `Hazard`, `RiskLevel`, `AgentEvent` |
| `frontend/lib/api.ts` | 7 | `getMountains`, `getMountain`. Base URL from `NEXT_PUBLIC_API_URL` |
| `frontend/lib/fixtures/run.json` | 7 | One finished five-agent run for the panel before the LLM is wired |
| `frontend/components/globe/` | 8–9 | React Three Fiber globe, markers, search, fly-to |
| `frontend/app/mountains/[slug]/page.tsx` | 9, 15 | Mountain route |
| `frontend/components/map/` | 15–16, 18 | Mapbox terrain, tiles, trails, pins |
| `frontend/components/panel/` | 23, 25 | Side panel, agent rows, hazard detail, hiker card |

`AgentEvent` shape, fixed in step 7:

```json
{ "run_id": "", "agent": "terrain|weather|trail|synthesizer|writer", "status": "waiting|running|done|error", "summary": "", "payload": {} }
```

### Backend

| Path | Step | Role |
|---|---|---|
| `backend/app/seed.py` | 5 | Loads `data/seed/` |
| `backend/app/routes/mountains.py` | 6, 13, 18 | List, detail, layer tile templates |
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
| `data/seed/mountains.json` | 5 | Rainier plus two static peaks |
| `data/seed/trails.geojson` | 5, then replaced in 14 | Trail lines |
| `data/seed/landslides.geojson` | 10, 14 | Pin source |
| `data/seed/sources.md` | 10 | URL and access date for each download |
| `data/raw/` | 10 | DEM and land cover. Gitignored |
| `data/processed/` | 11 | Feature table and derived rasters. Gitignored |
| `ml/scripts/build_features.py` | 11 | Slope, aspect, curvature, elevation, distance to drainage, land cover, wetness |
| `ml/scripts/train_susceptibility.py` | 12 | LightGBM, spatial holdout, `ml/artifacts/metrics.json` |
| `ml/scripts/render_tiles.py` | 13, 18 | XYZ tiles in EPSG:3857 |

## Invariants

- Risk levels are `low`, `moderate`, `high`, `extreme`.
- Bins: low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7.
- Rainier bbox: west -121.93, south 46.76, east -121.54, north 46.96.
- Tiles are Web Mercator XYZ. A tile that is offset from the ridges is a broken step 13 or 18, not a Mapbox setting to tweak later.
- Agents return Pydantic-validated JSON. Tools return precomputed facts. They do not scan the raster and they do not invent trail geometry.
