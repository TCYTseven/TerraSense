# Team handoff

State of TerraSense, written at the start of the build (Thursday, Sep 24, 2026) and updated after steps 1 to 10 (Friday, Sep 25, 2026). Written for the HackGT team and for an agent picking the repo up.

The two-minute version is [`TEAM_BRIEF.md`](TEAM_BRIEF.md). The product contract is [`../TerraSense.md`](../TerraSense.md). The ordered work is [`../implementation-steps.md`](../implementation-steps.md).

When this file and the code disagree, the code wins and this file gets fixed in the same change. When this file and the spec disagree about what to build, the spec wins.

## Start here

1. Read the decisions below. They are closed.
2. Open the checklist in [`../implementation-steps.md`](../implementation-steps.md). Do the first unchecked step on your track.
3. Frontend: `cd frontend && npm run dev` (port 3000). API: `cd backend && uvicorn app.main:app --reload --port 8000`. Setup is in the root README and each folder's `AGENTS.md`.
4. Before adding a control, read [`UX.md`](UX.md).

## The one-paragraph version

TerraSense shows landslide risk for Mount Rainier. A Next.js globe opens a Mapbox terrain view. A precomputed susceptibility model plus live rain from Open-Meteo produce a 72-hour probability layer. Five agents turn that layer into a ranger alert and a hiker sentence. Rangers read the alert in the app. Hikers see the sentence and one bypass. The demo is one mountain, run on demand with **Analyze now**.

## What exists

| Path | State |
|---|---|
| `frontend/` | Next.js 16.3.6, React 19, Tailwind 4, TypeScript. Dark dispatch theme, typed API client, the React Three Fiber globe with risk markers, search, fly-in, and `/mountains/[slug]`. No Mapbox yet. |
| `backend/` | FastAPI with `/health`, `/mountains`, `/mountains/{slug}`. Six-table schema in `app/schema.sql`, seed loader in `app/seed.py`. |
| `ml/` | `scripts/download_sources.py` (step 10). No model yet. |
| `data/` | `seed/mountains.json`, a rough `seed/trails.geojson`, `seed/sources.md`. `raw/` holds the DEM and land cover after the step 10 script runs. `seed/landslides.geojson` is pending. |
| `context/TerraSense.md` | Hackathon spec. This is the build target. |
| `context/implementation-steps.md` | Steps 1 to 25, ticked through step 9. |
| `context/docs/` | This set. |

Proven in a browser against a local API and Postgres: the globe loads three markers in their risk colors, hover shows name, risk, and refresh, search and marker clicks fly in and open the mountain page, and loading, error, and not-found states work. Unproven: everything from the Mapbox view on, and a hosted database.

## Decisions already made

Do not reopen these during the hackathon unless the demo is already rehearsed and the team writes the change into the spec.

- **One live mountain.** Mount Rainier, slug `mount-rainier`. Two other peaks are static globe markers.
- **Landslide and debris flow only.** Other hazard types stay out.
- **Two models.** LightGBM susceptibility is offline. The live score blends that raster with Open-Meteo rain. Weights stay named constants.
- **Five agents.** Terrain and Weather run in parallel, then Trail, Synthesizer, and Alert Writer. History is a tool, not an agent.
- **Two LLM providers and a router** (Sep 25, 2026). Gemini Flash and Grok. A router in code picks one per call and records why; the reasoning shows in a side panel. Either key alone works.
- **No alert channel** (Sep 25, 2026). Discord was dropped. The alert stays in the app. No SMS, email, Slack, accounts, or ack/dismiss.
- **Geometry is GeoJSON in JSON.** No PostGIS. Run state lives in the API process. No Redis.
- **Tiles are XYZ in EPSG:3857**, served by the API. No object storage.
- **The bypass is computed in Python** or hand-authored from a real second trail. The Trail Analyst explains it and does not invent a line.
- **Analyze now is the product.** There is no scheduled ingest job.
- **Publish the AUC you measure.** 0.85 is not a gate.
- **Modal is optional.** Use it only if a local Model B run is too slow to demo.

Shared numbers (bbox, peak, risk bins) live in the implementation steps under "Shared facts." Use those figures in code.

## Who does what next

| Track | Now | Then |
|---|---|---|
| Frontend | Step 15, the Mapbox terrain view in the map area of `/mountains/[slug]`. Needs `NEXT_PUBLIC_MAPBOX_TOKEN`. | Layer toggles (step 16), then the agent panel (step 23). |
| Backend | Provision the hosted Postgres and run the schema and seed. Then steps 20–21, the agent schemas and pipeline. | Analyze and the socket (step 22) after the agents exist. |
| ML and data | Finish step 10: run `download_sources.py --only landslides` on a network that reaches data.nasa.gov. | Feature table and LightGBM (steps 11–12) before anyone waits on tiles. |
| Product | Read the demo script aloud once. | Fill Devpost brackets after step 12 has a real AUC. |

## How an agent resumes

1. Read [`TEAM_BRIEF.md`](TEAM_BRIEF.md), this file's decisions, and [`UX.md`](UX.md) if the task touches UI.
2. Read the matching section of [`../TerraSense.md`](../TerraSense.md).
3. Take the next unchecked step in [`../implementation-steps.md`](../implementation-steps.md). Do not skip ahead on the same track.
4. Read [`CODE_REFERENCE.md`](CODE_REFERENCE.md) before adding a file, and update it in the same change.
5. Stay inside the spec's Out of Scope list.

## If you are behind

Drop work in this order. The demo still holds.

1. The two static globe markers.
2. The susceptibility toggle. Keep the 72-hour heat map.
3. A computed bypass. Keep a named bypass in the hiker sentence.
4. The Synthesizer as its own model call. Let Alert Writer merge the three reports.

Keep the globe, the heat map, and the agent stream.

## Known risks

| Risk | What to do |
|---|---|
| Raster work eats the weekend | Precompute Model A. Only Model B runs live |
| The heat map misses the ridges | XYZ tiles in EPSG:3857. Check alignment in step 16, not the night before the demo |
| Agents run long | Parallelize Terrain and Weather. Short JSON. Fast models for the first three |
| The starter UI leaks into the demo | Step 2 deletes the create-next-app page before any feature work |
