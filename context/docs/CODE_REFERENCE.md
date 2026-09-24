# Code reference

Map of the TerraSense repo. Update the matching section in the same change that adds, renames, or deletes a file.

Planned paths are labeled **planned**. They are not in the tree yet. Do not import them. When you create one, remove the planned label and document the real exports.

The product contract is [`../context/TerraSense.md`](../context/TerraSense.md). The build order is [`../context/implementation-steps.md`](../context/implementation-steps.md).

## What is in the tree

```
frontend/          Next.js app. Stock starter. Runs with npm run dev.
context/           Spec and the 25 implementation steps.
docs/              Team brief, handoff, UX, this file.
README.md          One-line pitch.
```

No `backend/`, `ml/`, or `data/` directory yet.

## Frontend (exists)

Next.js 16.3.6, React 19.2, Tailwind CSS 4, App Router, TypeScript. Package name `frontend`.

| File | What it is |
|---|---|
| `frontend/package.json` | Scripts: `dev`, `build`, `start`, `lint`. Dependencies are Next, React, and React DOM only. |
| `frontend/app/layout.tsx` | Root layout. Loads Geist Sans and Geist Mono as CSS variables. Metadata title is still "Create Next App". |
| `frontend/app/page.tsx` | Stock home page. Replace this in implementation step 2. |
| `frontend/app/globals.css` | Tailwind import and the default light/dark zinc tokens. Step 2 replaces these with the spec palette. |
| `frontend/next.config.ts` | Default Next config. |
| `frontend/postcss.config.mjs` | Tailwind PostCSS plugin. |
| `frontend/tsconfig.json` | Strict TypeScript. Path alias `@/*` → repo root of `frontend/`. |
| `frontend/eslint.config.mjs` | `eslint-config-next`. |

No components, no `lib/`, and no routes besides `/`.

## Planned layout

Create these as the steps call for them. Paths match [`../context/implementation-steps.md`](../context/implementation-steps.md).

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
| `backend/requirements.txt` | 3 | FastAPI, Uvicorn, Pydantic, HTTPX, Postgres driver |
| `backend/app/main.py` | 3 | App, CORS for `http://localhost:3000`, `GET /health` |
| `backend/app/schema.sql` | 4 | Six tables. Geometry as `jsonb` |
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
