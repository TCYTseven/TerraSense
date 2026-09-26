# TerraSense

Landslide hazard intelligence for one mountain, Mount Rainier. Built for HackGT.

TerraSense reads terrain and rain for Rainier, predicts where a landslide is likely in the next 72 hours, and turns that into a ranger alert and a hiker forecast.

The prediction comes from an ML model over satellite terrain, land cover, and rain. Five agents
then read that one map at the same time, each for something the model is blind to: the ground
under the zone, the weather around it, the miles hikers walk, the landslide record, and the other
66 trails on the mountain. A sixth agent reads all five and decides: three routes to keep hikers
off today, three that are safest, and what the park should do about it, from a line in the
newsletter to clearing the mountain.

```bash
curl 'http://localhost:8000/mountains/mount-rainier/advisory'   # after one Analyze run
```

## Setup

```bash
cp .env.example .env   # fill in values. .env is gitignored.
```

## Three commands

**1. Frontend dev server.** Next.js on http://localhost:3000.

```bash
cd frontend && npm install && npm run dev
```

**2. API dev server.** FastAPI on http://localhost:8000.

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m app.schema && python -m app.seed    # first run: create the tables, load data/seed/
uvicorn app.main:app --reload --port 8000
```

**Map layers and Analyze** need `ml/artifacts/susceptibility.tif` and tiles under `backend/tiles/`. From the repo root (Python 3.12+; on macOS, `brew install libomp` if LightGBM fails):

```bash
python3.12 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements.lock.txt
ml/.venv/bin/python ml/scripts/download_sources.py --only dem,landcover,landslides
ml/.venv/bin/python ml/scripts/build_features.py
ml/.venv/bin/python ml/scripts/train_susceptibility.py
ml/.venv/bin/python ml/scripts/render_tiles.py --layer susceptibility
```

After a live Analyze run has rendered Model B's probability layer, prove the full artifact set:

```bash
ml/.venv/bin/python ml/scripts/validate_pipeline.py --require-probability
```

Check API setup: `curl 'http://localhost:8000/health?verbose=1'`

No API keys, or no network to Gemini and xAI? `backend/AGENTS.md` has the offline fake-provider commands.

**3. Where the spec lives.**

- Product: [`context/TerraSense.md`](context/TerraSense.md)
- Build order and shared facts: [`context/implementation-steps.md`](context/implementation-steps.md)
- Team docs: [`context/docs/`](context/docs/README.md). Start with [`TEAM_BRIEF.md`](context/docs/TEAM_BRIEF.md).

## Who owns which folder

| Folder | Process | Track |
|---|---|---|
| `frontend/` | Next.js UI on port 3000 | Frontend |
| `backend/` | FastAPI on port 8000 | Backend and agents |
| `ml/` | Offline Python: downloads, features, model, tiles | ML and data |
| `data/` | Files. `seed/` is in git. `raw/` and `processed/` are gitignored | ML and data |
| `context/` | Spec, build steps, team docs | Product |

Coding agents start at [`AGENTS.md`](AGENTS.md). Each folder has its own `AGENTS.md`.
