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
python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

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
