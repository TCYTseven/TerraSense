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
| 20–22 | Agent schemas, tools, the agent pipeline, `POST /analyze`, `GET /runs/{id}`, `WS /runs/{id}/stream`, `GET /runs/{id}/advisory` |
| 33 | `previous_runs`, the run history log. `app/previous_runs.py`, `GET /history`, `GET /history/{run_id}` |

## The pipeline

```
terrain ─┐
weather ─┤
trail   ─┼─▶ synthesizer ─▶ writer
history ─┤
routes  ─┘
```

Five analysts fan out together, so the analyst stage costs the slowest one rather than the sum
(about 25 s against the real providers, not 90). The Risk Synthesizer is the only agent that sees
all five and the only one that decides: it returns the final severity and action, three routes to
keep hikers off, three that are safest today, and the ranger response, from a newsletter line to
an evacuation. The Alert Writer then turns that decision into the ranger and hiker copy.

`app/ml/model_b.py` (step 17) sits here but belongs to the ML track. Nothing imports it directly: `app/ml/probability.py` is the seam. It calls `model_b.run(rain)` when the module exists and uses the susceptibility map as a labeled stand-in until then, so steps 18 onward run before Model B lands.

`POST /api/v1/landslide-risk` is the stricter production classifier seam. It reads the canonical
event-time feature contract in `app/ml/risk_contract.py`, applies a persisted calibrated model,
and returns `HIGH_RISK`, `NOT_HIGH_RISK`, or fail-closed `UNCERTAIN`. Missing calibration,
forecast, static inputs, or in-domain evidence must not become a negative prediction.
Every in-domain answer with rain also carries `probability` (0 to 1), `probability_source`, the
shared `risk_level`, and an `estimate` block. Without a calibrated model, `probability` is the Model B
value at the clicked 30 m pixel, scored by the same Model B as the heat layer on today's rain, with
its 1 km cell, the logit terms behind it, and the held-out skill from the ML artifacts. It is a
relative risk index, not an absolute chance. The estimate never changes `state`. No rain, no
terrain, a blank pixel, or a point outside the box gives `probability: null`, never a dry-day number.
The agents' classification fact leaves the point estimate out.

## Rules

- Keep the API thin. Run state lives in the API process, keyed by `run_id`. No Redis, no PostGIS, no auth, no object storage.
- Geometry is GeoJSON stored in `jsonb` columns.
- Response shapes are a contract with `frontend/lib/types.ts`. Change both in the same commit.
- `mount-rainier` is always live. A step 32 pack goes live when `python -m app.seed` finds its susceptibility raster; every other summit is a static marker whose analyze falls back to the location run.
- Read settings from the root `.env`. Never log `DATABASE_URL`, `GEMINI_API_KEY`, or `XAI_API_KEY`.
- CORS allows the local Next.js origins. Add a deployed frontend with `CORS_ORIGINS`, not by editing code.
- A database that is down returns 503 `Database unavailable` within 5 s. `/health` never touches the database.
- Tools that agents call return precomputed facts. They do not scan rasters or invent trail geometry.
- Every model call goes through the router in `app/agents/router.py`, which picks Gemini Flash or Grok and records why. Do not call a provider directly.
- The ML model's output is the run's source of truth. Every agent calls `get_model_prediction` first and explains those numbers; none of them recomputes or argues with them. What an agent adds is what the model never saw: the trail network, the landslide record, the conditions, and what a ranger should do.
- The five analysts run in one `asyncio.gather`. Nothing in an analyst may read another analyst's payload: that would put the fan-out back in series. Only the Risk Synthesizer sees all five.
- `tests/test_contracts.py` pins the three seams other people build against: what Model B must return, the JSON schema each agent's output is sent to the providers as, and the JSON-nativeness of every payload that leaves the process. A numpy scalar or a datetime in a tool result is a 500 on the stream, not a rounding difference, so it is caught there.
- The Risk Synthesizer is the only agent that decides anything, and code checks its answer in `app/agents/advisory.py`. A route it names must be on the shortlist the code built from the scored catalog, and its ranger posture cannot outrun the severity the run reached. Clamps are recorded as checks, never silent.

## Commands

Run these from `backend/`:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m app.schema            # create the tables in DATABASE_URL. Safe to re-run
python -m app.schema --reset    # drop the core tables, then recreate them. previous_runs is kept
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
curl localhost:8000/runs/<run_id>/advisory        # the run's whole conclusion: 3 routes to avoid, 3 safe, the ranger response
curl localhost:8000/mountains/mount-rainier/advisory   # the newest one, after any finished run
curl localhost:8000/history                       # step 33: every run logged, newest first
curl localhost:8000/history/<run_id>              # one logged run, with every agent trace
python -m pytest                # schemas, router, providers, tools, the guard rails, the contracts, and the pipeline (fake LLMs; needs DATABASE_URL)
python -m app.agents.pipeline   # the agents once, with the advisory printed. Needs GEMINI_API_KEY or XAI_API_KEY
```

No keys, or no network to the providers? Run the fake APIs and point the providers at them. Every answer is labeled `fake-...`:

```bash
uvicorn tests.fake_llm:app --port 8090 &
GEMINI_API_KEY=fake XAI_API_KEY=fake GEMINI_BASE_URL=http://localhost:8090 XAI_BASE_URL=http://localhost:8090 \
  python -m app.agents.pipeline --fixture-rain
```

Set `DB` to `LOCAL` or `PROD` and the matching `DATABASE_URL_LOCAL` or `DATABASE_URL_PROD` in the root `.env` (Tiger Cloud / TimescaleDB is Postgres-compatible). Legacy single `DATABASE_URL` still works. Postgres 13+ (`gen_random_uuid()` built in).
