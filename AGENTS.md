# TerraSense agent guide

TerraSense is a HackGT build: landslide hazard intelligence for one mountain, Mount Rainier. This file orients any coding agent that opens the repo. Each top-level folder has its own `AGENTS.md` with the commands and rules for that folder.

## Read first

1. [`context/docs/TEAM_BRIEF.md`](context/docs/TEAM_BRIEF.md): status and tracks.
2. [`context/TerraSense.md`](context/TerraSense.md): the product. If a feature is not in its Hackathon Scope, do not build it.
3. [`context/implementation-steps.md`](context/implementation-steps.md): the 30 steps, split into pending and done, and the shared facts.
4. The `AGENTS.md` in the folder you are about to change.
5. [`context/docs/CODE_REFERENCE.md`](context/docs/CODE_REFERENCE.md) before you add, rename, or delete a file.

## Who owns which folder

| Folder | Process | Track | Steps |
|---|---|---|---|
| `frontend/` | Next.js on port 3000 | Frontend | 2, 7–9, 15–16, 23, 25, 29–30 |
| `backend/` | FastAPI on port 8000 | Backend and agents | 3–6, 20–22, 24, 28 |
| `ml/` | Offline Python scripts. No server | ML and data | 10–14, 17–19, 26–27 |
| `data/` | Files only | ML and data | 5, 10, 14 |
| `context/` | Spec, steps, team docs | Product | Demo script, Devpost |

Two files cross folders on purpose. `backend/app/ml/model_b.py` (step 17) belongs to the ML track because the API calls it live. `backend/tiles/` holds PNGs that `ml/scripts/render_tiles.py` writes (steps 13 and 18).

## Working together

Several agents and people build in parallel. These rules keep them out of each other's way.

1. **Claim a step before you build it.** Check `git branch -r` and the open pull requests for the step number first. Claim by pushing a branch named `step-<N>-<short-name>`, or by opening a draft pull request titled `Step N: <checklist title>`.
2. **Finish steps in order on your track.** After step 6, the globe (7–9) and the data work (10–14) can run at the same time.
3. **One step, one commit.** Title it `Step N: <checklist title>`. In the same commit, tick the step's box in `context/implementation-steps.md` and update `context/docs/CODE_REFERENCE.md` for every file you add, rename, or delete.
4. **Stay in your folder.** If a step needs a change in another track's folder, keep it small and name it in the commit body.
5. **Contracts are the seams between folders.** Change both sides in one commit:
   - API responses: Pydantic models in `backend/app/` and the types in `frontend/lib/types.ts`.
   - Seed formats: `data/AGENTS.md`.
   - Shared facts: the table in `context/implementation-steps.md`. Code copies them as named constants.
6. **Prove it before you commit.** Run the step's "Done when" check plus the folder's checks. Say what you ran in the commit body.
7. **Never commit secrets.** `.env` is gitignored. A new variable goes into `.env.example` with a one-line comment.

## Subagents

`.claude/agents/` defines one builder per track and one reviewer:

| Agent | Use it for |
|---|---|
| `frontend-builder` | A step in `frontend/` |
| `backend-builder` | A step in `backend/` |
| `ml-data-builder` | A step in `ml/` or `data/` |
| `step-reviewer` | Checking a finished step against its "Done when" before it merges |

A lead agent can hand one step to the matching builder, then ask `step-reviewer` to check the diff.

## Shared facts

Copy these. Do not re-derive them.

- Live mountain: Mount Rainier, slug `mount-rainier`, peak 46.8523, -121.7603, elevation 4392 m.
- Bounding box `[-121.93, 46.76, -121.54, 46.96]` (west, south, east, north).
- Risk levels `low`, `moderate`, `high`, `extreme`. Probability bins: low < 0.2, moderate 0.2–0.45, high 0.45–0.7, extreme > 0.7.
- Map tiles are XYZ PNG in EPSG:3857.

## Setup

```bash
cp .env.example .env    # one env file at the repo root, read by frontend/ and backend/
```

Folder commands live in each folder's `AGENTS.md`.
