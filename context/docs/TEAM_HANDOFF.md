# Team handoff

State of TerraSense, written at the start of the build (Thursday, Sep 24, 2026) and updated Saturday, Sep 26, 2026. Written for the HackGT team and for an agent picking the repo up.

The two-minute version is [`TEAM_BRIEF.md`](TEAM_BRIEF.md). The product contract is [`../TerraSense.md`](../TerraSense.md). The ordered work is [`../implementation-steps.md`](../implementation-steps.md). What is left today is [`../9-26-todo.md`](../9-26-todo.md).

When this file and the code disagree, the code wins and this file gets fixed in the same change. When this file and the spec disagree about what to build, the spec wins.

## Start here

1. Read the decisions below. They are closed.
2. Take the next open item in [`../9-26-todo.md`](../9-26-todo.md). Do not rebuild steps 10, 11, 12, 14, or 17. They are on `origin/step-10-local-nasa-export`.
3. Frontend: `cd frontend && npm run dev` (port 3000). API: `cd backend && uvicorn app.main:app --reload --port 8000`. Setup is in the root README and each folder's `AGENTS.md`.
4. Before adding a control, read [`UX.md`](UX.md).

## The one-paragraph version

TerraSense shows landslide risk for Mount Rainier. A Next.js globe opens a MapLibre terrain view (Mapbox satellite is optional). A precomputed susceptibility model plus live rain from Open-Meteo produce a 72-hour probability layer. On main that layer is still the susceptibility stand-in, until Model B is merged. Seven agents turn a run into a ranger alert and Reactive Measures. Rangers read the alert in the app. The demo is one mountain, run on demand with **Analyze now**.

## What exists

| Path | State |
|---|---|
| `frontend/` | Next.js 16, React 19, Tailwind 4, TypeScript. Light home theme, React Three Fiber globe, search, fly-in, and the hill detail card at `/mountains/[slug]`. MapLibre terrain, heat map, susceptibility toggle, five trail markers. **Analyze now** on a live mountain streams the real run. Trail scores come from the saved heat map. |
| `backend/` | FastAPI: health, mountains, layers, analyze, the run socket, advisory, forecast. Seven-agent pipeline. Six-table schema and seed. Mountain catalog loader. Verified on a local Postgres 16. No hosted database yet. |
| `ml/` | Download, feature stack, knowledge-driven susceptibility, tiles, trails, and the bypass network are on main. LightGBM training and Model B are on `origin/step-10-local-nasa-export`. |
| `data/` | `seed/mountains.json` (648 peaks), `seed/mountains_test.json` (138, the default seed), Rainier trails, segments, and the trail network. `seed/landslides.geojson` is on the NASA-export branch, not on main. |
| `context/` | Spec, the 31 steps, and [`../9-26-todo.md`](../9-26-todo.md). |

Proven in a browser against a local API and Postgres: the globe, search, fly-in, the hill card, and loading, error, and not-found states. **Analyze now** is wired to the API. Unproven on main: a live Gemini or xAI call, historical pins, Model B moving the heat map, the mountain panel, and a hosted database.

## Decisions already made

Do not reopen these during the hackathon unless the demo is already rehearsed and the team writes the change into the spec.

- **One live mountain.** Mount Rainier, slug `mount-rainier`. Other peaks are catalog markers.
- **Landslide and debris flow only.** Other hazard types stay out.
- **Two models.** LightGBM susceptibility is offline. The live score blends that raster with Open-Meteo rain. Weights stay named constants.
- **Seven agents** (Sep 25, 2026). Terrain, Weather, Trail, History, and Route Scout run in parallel, then the Risk Synthesizer, then the Alert Writer. The hill card shows five rows. History and Route Scout fold into Trails.
- **Two LLM providers and a router** (Sep 25, 2026). Gemini Flash and Grok. A router in code picks one per call and records why. Either key alone works. The trace shows on the agent card, not in a side panel.
- **No alert channel** (Sep 25, 2026). Discord was dropped. The alert stays in the app. No SMS, email, Slack, accounts, or ack/dismiss.
- **Geometry is GeoJSON in JSON.** No PostGIS. Run state lives in the API process. No Redis.
- **Tiles are XYZ in EPSG:3857**, served by the API. No object storage.
- **The map is MapLibre GL** with AWS Terrain Tiles. A Mapbox token switches the relief to satellite. It is not required.
- **The bypass is computed in Python** from the OpenStreetMap trail network. The Trail Analyst explains it and does not invent a line.
- **Analyze now is the product.** There is no scheduled ingest job.
- **Publish the AUC you measure.** 0.85 is not a gate. Terrain: 0.82 regional, 0.60 on Rainier. Rain trigger: 0.75.
- **Modal is optional.** Use it only if a local Model B run is too slow to demo.

Shared numbers (bbox, peak, risk bins) live in the implementation steps under "Shared facts." Use those figures in code.

## Who does what next

| Track | Now | Then |
|---|---|---|
| Frontend | Finish step 31: trail scores, overall score, and preventative measures from a real run. | Mountain panel (step 29), then playback (step 30). |
| Backend | Nothing until pressure points exist. | Simulate, the stream, and the callouts (step 28). |
| ML and data | Merge `origin/step-10-local-nasa-export`. | Pressure points (step 26), then the runout (step 27). |
| Product | Read the demo script aloud once. | Fill the Devpost AUC after the merge. Rehearse with real keys. |

## How an agent resumes

1. Read [`TEAM_BRIEF.md`](TEAM_BRIEF.md), this file's decisions, and [`UX.md`](UX.md) if the task touches UI.
2. Read the matching section of [`../TerraSense.md`](../TerraSense.md).
3. Take the next open item in [`../9-26-todo.md`](../9-26-todo.md). Do not skip ahead on the same track, and do not rebuild a step that already has a branch.
4. Read [`CODE_REFERENCE.md`](CODE_REFERENCE.md) before adding a file, and update it in the same change.
5. Stay inside the spec's Out of Scope list.

## If you are behind

Drop work in this order. The demo still holds.

1. The callouts (step 28's model call; keep template callouts), then the simulation (steps 27, 28, 30). Keep step 29's panel, or let the click fly straight in as it does today.
2. The extra globe markers. Rainier alone still demos.
3. The susceptibility toggle (step 16). Keep the 72-hour heat map.
4. A computed bypass (step 19). Keep a named bypass in the hiker sentence.
5. The Synthesizer as its own model call (step 21). Let the Alert Writer merge the five reports.
6. Step 31's last check: the five trails against the advisory after a fake-LLM run.

Keep the globe, the heat map, and the agent stream.

## Known risks

| Risk | What to do |
|---|---|
| Someone rebuilds steps 10–17 | Merge `origin/step-10-local-nasa-export`. The files are already there |
| Raster work eats the weekend | Precompute Model A. Only Model B runs live |
| The heat map misses the ridges | XYZ tiles in EPSG:3857. Check alignment on the merged tiles, not the night before the demo |
| Agents run long | The five analysts already run in parallel. Short JSON. Fast models |
| No hosted database and no live keys | That is the "Before the demo" item. Keep one finished run on screen |
