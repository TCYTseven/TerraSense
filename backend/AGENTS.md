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

`app/ml/model_b.py` (step 17) sits here but belongs to the ML track. Nothing imports it directly: `app/ml/probability.py` is the seam. It calls `model_b.run(rain)` when the module exists and uses the susceptibility map as a labeled stand-in until then, so steps 18 onward run before Model B lands.

## Rules

- Keep the API thin. Run state lives in the API process, keyed by `run_id`. No Redis, no PostGIS, no auth, no object storage.
- Geometry is GeoJSON stored in `jsonb` columns.
- Response shapes are a contract with `frontend/lib/types.ts`. Change both in the same commit.
- Only `mount-rainier` is live. Reject analyze when `is_live` is false.
- Read settings from the root `.env`. Never log `DATABASE_URL`, `GEMINI_API_KEY`, or `XAI_API_KEY`.
- CORS allows the local Next.js origins. Add a deployed frontend with `CORS_ORIGINS`, not by editing code.
- A database that is down returns 503 `Database unavailable` within 5 s. `/health` never touches the database.
- Tools that agents call return precomputed facts. They do not scan rasters or invent trail geometry.
- Every model call goes through the router in `app/agents/router.py`, which picks Gemini Flash or Grok and records why. Do not call a provider directly.

## Commands

Run these from `backend/`:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m app.schema            # create the six tables in DATABASE_URL. Safe to re-run
python -m app.schema --reset    # drop the six tables, then recreate them
python -m app.seed               # load data/seed/: three mountains, Rainier's trails, the hero trail's segments. Safe to re-run
python -m app.assessment         # step 18: score the map, the hero trail, and the hazard zone. Writes nothing
python -m app.assessment --save  # also render the probability tiles, store segment risk, and save a preview hazard
uvicorn app.main:app --reload --port 8000
curl localhost:8000/health
curl localhost:8000/mountains
curl localhost:8000/mountains/mount-rainier
curl localhost:8000/mountains/mount-rainier/layers/probability
curl -X POST localhost:8000/mountains/mount-rainier/analyze   # step 22: { run_id }; follow ws://localhost:8000/runs/<run_id>/stream
curl localhost:8000/runs/<run_id>
python -m pytest                # schemas, router, providers, tools, and the pipeline (fake LLMs; needs DATABASE_URL)
python -m app.agents.pipeline   # step 21: the five agents once, printed. Needs GEMINI_API_KEY or XAI_API_KEY
```

No keys, or no network to the providers? Run the fake APIs and point the providers at them. Every answer is labeled `fake-...`:

```bash
uvicorn tests.fake_llm:app --port 8090 &
GEMINI_API_KEY=fake XAI_API_KEY=fake GEMINI_BASE_URL=http://localhost:8090 XAI_BASE_URL=http://localhost:8090 \
  python -m app.agents.pipeline --fixture-rain
```

`DATABASE_URL` in the root `.env` can point at Neon, Supabase, or a local Postgres 13 or newer (`gen_random_uuid()` is built in from 13).
