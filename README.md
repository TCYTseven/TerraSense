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

### Production 72-hour classifier

The production path is a separate event-time classifier for
`P(rainfall-triggered landslide in a 1 km cell during the next 72 hours)`.
It uses a canonical feature table, spatial-temporal holdouts, held-out calibration,
validated high-risk thresholds, OOD checks, and the states `HIGH_RISK`,
`NOT_HIGH_RISK`, and `UNCERTAIN`. See [`context/docs/production-risk.md`](context/docs/production-risk.md).

The reproducible workflow is:

```bash
ml/.venv/bin/python ml/scripts/download_risk_source.py --help
ml/.venv/bin/python ml/scripts/build_risk_samples.py --dynamic data/processed/dynamic/hourly.parquet --out data/processed/feature_tables/risk_samples.parquet
ml/.venv/bin/python ml/scripts/build_static_features.py --stack data/processed/features.tif --out data/processed/static/static_cells.parquet --json-out data/processed/static/static_cells.json
ml/.venv/bin/python ml/scripts/build_risk_dataset.py --samples data/processed/feature_tables/risk_samples.parquet --labels data/processed/labels/coolr.geojson --out data/processed/feature_tables/risk_training.parquet
ml/.venv/bin/python ml/scripts/train_risk_model.py --table data/processed/feature_tables/risk_training.parquet
ml/.venv/bin/python ml/scripts/backtest_risk_model.py --table data/processed/feature_tables/risk_training.parquet
```

The source downloader records provenance but does not fabricate provider data or
convert arbitrary raw products silently. Historical IMERG/ERA5-Land and archived
forecast data must be normalized into the documented schema before training. Until
real timestamped data and calibrated artifacts exist under `ml/artifacts/`, the
production endpoint intentionally returns `UNCERTAIN`. It still answers with
`probability`, a 0 to 1 chance of a landslide in the next 72 hours. That chance is
the Model B estimate under the point, read from the same map as the heat layer, and
`probability_source: "model_b_estimate"` says so. A calibrated classifier's
probability replaces it once one exists. `probability` is `null` only outside the
Rainier study box, without rain data, or without terrain data.

```bash
curl -X POST http://localhost:8000/api/v1/landslide-risk \
  -H 'Content-Type: application/json' \
  -d '{"latitude":46.8523,"longitude":-121.7603}'
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
