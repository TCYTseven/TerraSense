# Team handoff

State of TerraSense at the start of the build (Thursday, Sep 24, 2026). Written for the HackGT team and for an agent picking the repo up.

The two-minute version is [`TEAM_BRIEF.md`](TEAM_BRIEF.md). The product contract is [`../TerraSense.md`](../TerraSense.md). The ordered work is [`../implementation-steps.md`](../implementation-steps.md).

When this file and the code disagree, the code wins and this file gets fixed in the same change. When this file and the spec disagree about what to build, the spec wins.

## Start here

1. Read the decisions below. They are closed.
2. Open the checklist in [`../implementation-steps.md`](../implementation-steps.md). Do the first unchecked step on your track.
3. Frontend is `cd frontend && npm run dev`. There is no API process yet.
4. Before adding a control, read [`UX.md`](UX.md).

## The one-paragraph version

TerraSense shows landslide risk for Mount Rainier. A Next.js globe opens a Mapbox terrain view. A precomputed susceptibility model plus live rain from Open-Meteo produce a 72-hour probability layer. Five agents turn that layer into a ranger alert and a hiker sentence. The alert posts to Discord. Hikers see the sentence and one bypass. The demo is one mountain, run on demand with **Analyze now**.

## What exists

| Path | State |
|---|---|
| `frontend/` | Next.js 16.3.6, React 19, Tailwind 4, App Router, TypeScript. Stock starter page. Geist fonts loaded. No Mapbox, no globe, no API client. |
| `context/TerraSense.md` | Hackathon spec. This is the build target. |
| `context/implementation-steps.md` | Steps 1–25. |
| `docs/` | This set. |
| `backend/`, `ml/`, `data/` | Not created. |

Proven: `npx create-next-app` completed and installed dependencies. Unproven: every product behavior in the demo script.

## Decisions already made

Do not reopen these during the hackathon unless the demo is already rehearsed and the team writes the change into the spec.

- **One live mountain.** Mount Rainier, slug `mount-rainier`. Two other peaks are static globe markers.
- **Landslide and debris flow only.** Other hazard types stay out.
- **Two models.** LightGBM susceptibility is offline. The live score blends that raster with Open-Meteo rain. Weights stay named constants.
- **Five agents.** Terrain and Weather run in parallel, then Trail, Synthesizer, and Alert Writer. Discord is a webhook call, not an agent. History is a tool, not an agent.
- **One alert channel.** Discord. No SMS, email, Slack, accounts, or ack/dismiss.
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
| Frontend | Step 2, the dark shell. Replace the starter page. | Globe (steps 8–9) as soon as `GET /mountains` exists. Until then, three hardcoded markers are acceptable only if they match the seed file. |
| Backend | Steps 3–6. Health check, schema, seed, mountain reads. | Analyze and the socket (step 22) after the agents exist. |
| ML and data | Step 10. Download the Rainier DEM, one land-cover raster, and landslide points. | Feature table and LightGBM (steps 11–12) before anyone waits on tiles. |
| Product | Create the Discord webhook and put the URL in an untracked env file. Read the demo script aloud once. | Fill Devpost brackets after step 12 has a real AUC. |

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

Keep the globe, the heat map, the agent stream, and the Discord message.

## Known risks

| Risk | What to do |
|---|---|
| Raster work eats the weekend | Precompute Model A. Only Model B runs live |
| The heat map misses the ridges | XYZ tiles in EPSG:3857. Check alignment in step 16, not the night before the demo |
| Agents run long | Parallelize Terrain and Weather. Short JSON. Fast models for the first three |
| Discord fails on stage | Keep the alert text on screen, and keep a screenshot of a successful post |
| The starter UI leaks into the demo | Step 2 deletes the create-next-app page before any feature work |
