# Team brief

The short version for HackGT. The full picture is in [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md). The product is in [`../TerraSense.md`](../TerraSense.md). Open work is [`../9-26-todo.md`](../9-26-todo.md).

Written Thursday, Sep 24, 2026. Status updated Saturday, Sep 26, 2026.

## Status right now

- The hackathon scope is locked. One live mountain (Mount Rainier), landslide risk only, seven agents, the mountain page, one mountain panel with a runout simulation. Discord was dropped on Sep 25, 2026: the ranger alert stays in the app.
- Steps 1–9, 13, 15, 16, and 18–25 are done on main. Step 24 was dropped. The globe, the mountain page, the heat map, the bypass, and the agent pipeline all run.
- Steps 10, 11, 12, 14, and 17 are built on `origin/step-10-local-nasa-export` and are not on main. Merge that branch. Do not rebuild it. On main there are still no landslide points, LightGBM is untrained, and the heat map is the susceptibility stand-in.
- Step 31 is half done. **Analyze now** on Rainier streams the seven agents into the five cards, and Reactive Measures come from the advisory. Trail scores, the overall score, and preventative measures come from the saved heat map. Left: the fake-LLM check against the advisory.
- Steps 26–30 (pressure points, runout, simulate, the mountain panel) are not started.
- The default globe seed is 138 peaks (`SEED_MODE=mountainstest`), drawn 50 at a time. `data/seed/mountains.json` has 648. No hosted Postgres yet, and no live Gemini or xAI call has run.
- Each folder has an `AGENTS.md` harness, and `.claude/agents/` defines a builder per track plus a reviewer. Start at the root [`AGENTS.md`](../../AGENTS.md).

## What you are building

A judge spins a 3D globe, opens Mount Rainier, reads the slopes most likely to fail, watches a debris-flow simulation, flies into the mountain page, sees the heat map and five trails, watches the agents run, and reads the Reactive Measures.

Other peaks are catalog markers with a fixed risk color. They do not run analysis.

## Setup

1. Read [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md) section "Decisions already made" before you pick a library.
2. Copy `.env.example` to `.env` at the repo root, then follow the commands in the root [`README.md`](../../README.md): the API on port 8000, the frontend on port 3000.
3. Keys you will need, and do not commit: a Gemini key and an xAI key (either alone works), `DATABASE_URL`. A Mapbox token is optional. Open-Meteo needs no key.
4. Agree on the shared facts in the implementation steps (Rainier bbox, slugs, risk bins) and use them in every track.

## Tracks

The spec assumes four people. Claim a step in the repo or in chat so two people do not start the same step. Check `git branch -r` first. `step-10-local-nasa-export` already claims 10, 11, 12, 14, and 17.

| Track | Steps | Next |
|---|---|---|
| Frontend | 2, 7–9, 15–16, 23, 25, 29–31 | Finish step 31's trail scores, then the mountain panel (29–30) |
| Backend | 3–6, 20–22, 28 | Simulate, the stream, and the callouts (step 28), after pressure points exist |
| ML and data | 10–14, 17–19, 26–27 | Merge the NASA-export branch, then rank pressure points (26) and trace a runout (27) |
| Product and pitch | Demo script, Devpost blanks | Rehearse with real keys. Write the measured AUC into the Devpost draft after the merge |

## If you change the plan

Change [`context/TerraSense.md`](../TerraSense.md) when the product changes, and [`context/implementation-steps.md`](../implementation-steps.md) when the order changes. Update [`CODE_REFERENCE.md`](CODE_REFERENCE.md) in the same change that adds a file. Tick today's open list in [`../9-26-todo.md`](../9-26-todo.md) when a pending item lands.

A feature in the Out of Scope section needs a team decision written into the spec before anyone starts it.
