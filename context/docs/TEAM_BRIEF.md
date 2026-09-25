# Team brief

The short version for HackGT. The full picture is in [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md). The product is in [`../TerraSense.md`](../TerraSense.md).

Written Thursday, Sep 24, 2026. Status updated Friday, Sep 25, 2026, after steps 1 to 10.

## Status right now

- The hackathon scope is locked. One live mountain (Mount Rainier), landslide risk only, five agents, one Discord alert, one hiker card.
- [`context/implementation-steps.md`](../implementation-steps.md) is the build order. Steps 1 to 9 are done. Step 10 is partial: the DEM and land cover are downloaded, but the landslide points are pending because data.nasa.gov was unreachable from the build container. See [`data/seed/sources.md`](../../data/seed/sources.md).
- `frontend/` is the dark globe: three risk markers from the API, hover cards, a search box, a 1.5 s fly-in, and the `/mountains/[slug]` page. The Mapbox view (step 15) is next on this track.
- `backend/` serves `/health`, `/mountains`, and `/mountains/{slug}` from Postgres. It was verified on a local Postgres 16. No hosted database exists yet: provision Neon or Supabase, set `DATABASE_URL`, then run `python -m app.schema && python -m app.seed` from `backend/`.
- The demo script runs up to "open Mount Rainier". Everything from the heat map on is still to build.
- Each folder has an `AGENTS.md` harness, and `.claude/agents/` defines a builder per track plus a reviewer. Start at the root [`AGENTS.md`](../../AGENTS.md).

## What you are building

A judge spins a 3D globe, opens Mount Rainier, sees a 72-hour landslide heat map, watches five agents run, sees a Discord message, and reads a hiker card that names a bypass.

Two other mountains are dots on the globe with a fixed risk color. They do not run analysis.

## Setup

1. Read [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md) section "Decisions already made" before you pick a library.
2. Copy `.env.example` to `.env` at the repo root, then follow the three commands in the root [`README.md`](../../README.md): the API on port 8000, the frontend on port 3000.
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

Change [`context/TerraSense.md`](../TerraSense.md) when the product changes, and [`context/implementation-steps.md`](../implementation-steps.md) when the order changes. Update [`CODE_REFERENCE.md`](CODE_REFERENCE.md) in the same change that adds a file.

A feature in the Out of Scope section needs a team decision written into the spec before anyone starts it.
