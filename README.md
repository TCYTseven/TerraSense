# TerraSense

Landslide hazard intelligence for one mountain, Mount Rainier. Built for HackGT.

TerraSense reads terrain and rain for Rainier, predicts where a landslide is likely in the next 72 hours, and turns that into a ranger alert and a hiker forecast.

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

**Map layers and Analyze** need `ml/artifacts/susceptibility.tif` and tiles under `backend/tiles/`. From the repo root (Python 3.12+, `pip install -r ml/requirements.txt`; on macOS, `brew install libomp` if LightGBM fails):

```bash
python ml/scripts/download_sources.py --only dem,landcover
python ml/scripts/build_features.py && python ml/scripts/train_susceptibility.py
PYTHONPATH=backend python ml/scripts/render_tiles.py
```

Check setup: `curl 'http://localhost:8000/health?verbose=1'`

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
