# Team brief

The short version for HackGT. The full picture is in [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md). The product is in [`../context/TerraSense.md`](../context/TerraSense.md).

Written Thursday, Sep 24, 2026. The tree at that moment is the spec, the 25-step plan, and a stock Next.js app.

## Status right now

- The hackathon scope is locked. One live mountain (Mount Rainier), landslide risk only, five agents, one Discord alert, one hiker card.
- [`context/implementation-steps.md`](../context/implementation-steps.md) is the build order. Step 1 is next. The Next.js app in `frontend/` already exists, so the scaffold half of step 1 is done.
- `frontend/` is still the create-next-app starter. It is light-themed boilerplate. It is not the globe.
- There is no `backend/`, no `ml/`, no database, and no seed data.
- Nothing in the demo script runs yet.

## What you are building

A judge spins a 3D globe, opens Mount Rainier, sees a 72-hour landslide heat map, watches five agents run, sees a Discord message, and reads a hiker card that names a bypass.

Two other mountains are dots on the globe with a fixed risk color. They do not run analysis.

## Setup

1. Read [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md) section "Decisions already made" before you pick a library.
2. `cd frontend && npm install && npm run dev` shows the starter page on port 3000.
3. Keys you will need, and do not commit: Mapbox token, one LLM provider key, `DATABASE_URL`, Discord webhook URL. Open-Meteo needs no key.
4. Agree on the shared facts in the implementation steps (Rainier bbox, slugs, risk bins) and use them in every track.

## Tracks

The spec assumes four people. Claim a track in the repo or in chat so two people do not start the same step.

| Track | Steps | First output |
|---|---|---|
| Frontend | 2, 7–9, 15–16, 23, 25 | Dark full-bleed shell, then the globe |
| Backend | 3–6, 22, 24 | FastAPI `/health`, then `GET /mountains` |
| ML and data | 10–14, 17–19 | Rainier DEM on disk, then a susceptibility raster |
| Product and pitch | Demo script, Devpost blanks, Discord channel | A webhook URL and a two-minute script the team has read aloud |

Steps 7–9 can use the API from step 6. Steps 10–14 can start as soon as the bounding box is agreed. Do not wait on each other past that.

## If you change the plan

Change [`context/TerraSense.md`](../context/TerraSense.md) when the product changes, and [`context/implementation-steps.md`](../context/implementation-steps.md) when the order changes. Update [`CODE_REFERENCE.md`](CODE_REFERENCE.md) in the same change that adds a file.

A feature in the Out of Scope section needs a team decision written into the spec before anyone starts it.
