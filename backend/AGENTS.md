# Backend agent guide

FastAPI service for TerraSense. Track: backend and agents. Serves http://localhost:8000.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## Steps this folder owns

| Step | Adds |
|---|---|
| 3 | `requirements.txt`, `app/main.py` with `GET /health` and CORS for http://localhost:3000 |
| 4 | `app/schema.sql`, six tables, geometry as `jsonb` |
| 5 | `app/seed.py`, loads `data/seed/` |
| 6 | `GET /mountains`, `GET /mountains/{slug}` |
| 13, 18 | `GET /mountains/{slug}/layers/{layer}` returns a tile URL template. Tiles live in `tiles/` |
| 20–22 | Agent schemas, tools, the five-agent pipeline, `POST /analyze`, `GET /runs/{id}`, `WS /runs/{id}/stream` |
| 24 | Discord webhook post |

`app/ml/model_b.py` (step 17) sits here but belongs to the ML track.

## Rules

- Keep the API thin. Run state lives in the API process, keyed by `run_id`. No Redis, no PostGIS, no auth, no object storage.
- Geometry is GeoJSON stored in `jsonb` columns.
- Response shapes are a contract with `frontend/lib/types.ts`. Change both in the same commit.
- Only `mount-rainier` is live. Reject analyze when `is_live` is false.
- Read settings from the root `.env`. Never log `DATABASE_URL`, `LLM_API_KEY`, or `DISCORD_WEBHOOK_URL`.
- CORS allows the local Next.js origins. Add a deployed frontend with `CORS_ORIGINS`, not by editing code.
- A database that is down returns 503 `Database unavailable` within 5 s. `/health` never touches the database.
- Tools that agents call return precomputed facts. They do not scan rasters or invent trail geometry.

## Commands

Run these from `backend/`:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.schema            # create the six tables in DATABASE_URL. Safe to re-run
python -m app.schema --reset    # drop the six tables, then recreate them
python -m app.seed               # load data/seed/: three mountains, Rainier's trails, the hero trail's segments. Safe to re-run
uvicorn app.main:app --reload --port 8000
curl localhost:8000/health
curl localhost:8000/mountains
curl localhost:8000/mountains/mount-rainier
python -m app.ml.model_b         # step 17: rain totals and the probability summary for Rainier
OPEN_METEO_FIXTURE=fixtures/open_meteo_storm.json python -m app.ml.model_b   # same, offline, with a synthetic storm
```

`DATABASE_URL` in the root `.env` can point at Neon, Supabase, or a local Postgres 13 or newer (`gen_random_uuid()` is built in from 13).
