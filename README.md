# TerraSense

Landslide hazard intelligence for Mount Rainier.

Predicts landslides up to 72 hours ahead, using ML and multiple agents for risk and trail safety recommendations.

```bash
curl 'http://localhost:8000/mountains/mount-rainier/advisory'
```

## Quick Setup

```bash
cp .env.example .env   # fill in your values
```

## Run it locally

**Frontend (Next.js):**
```bash
cd frontend && npm install && npm run dev
```

**Backend API (FastAPI, recommended way):**
```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.schema
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

**See API health:**  
```bash
curl 'http://localhost:8000/health?verbose=1'
```

**Docs:**  
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
- Build: [`context/implementation-steps.md`](context/implementation-steps.md)
- Team: [`context/docs/TEAM_BRIEF.md`](context/docs/TEAM_BRIEF.md)

## Folder guide

| Folder      | What                              |
|-------------|-----------------------------------|
| `frontend/` | Next.js UI (port 3000)            |
| `backend/`  | FastAPI & agents (port 8000)      |
| `ml/`       | ML, features, tiles, model stuff  |
| `data/`     | Data (only `seed/` is in git)     |
| `context/`  | Specs and docs                    |

Coding agents live in [`AGENTS.md`](AGENTS.md) (each folder has one).
