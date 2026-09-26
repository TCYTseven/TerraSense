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
