# Pending — Saturday, Sep 26, 2026

Open work only. Build notes stay in [implementation-steps.md](implementation-steps.md).

## Merge

- [ ] Merge `origin/step-10-local-nasa-export` into main. It holds steps 10, 11, 12, 14, and 17. Main does not. Do not rebuild them. The branch is 7 commits ahead of `7ca0f8d`; main is 6 commits ahead of that same point (catalog, live **Analyze now**).
  - **10.** `data/seed/landslides.geojson`: 4 NASA events and 33 Washington inventory labels.
  - **11.** Labeled feature table, 1,224 rows, on the 30 m stack.
  - **12.** LightGBM trained. Held-out spatial AUC 0.715. Susceptibility tiles rendered.
  - **14.** 37 historical pins. The 67 trails and 55 Skyline segments are already on main.
  - **17.** `backend/app/ml/model_b.py`: susceptibility plus forecast rain and antecedent moisture.

## Build

- [ ] **26.** Rank the pressure points. `backend/app/ml/pressure.py` and `GET /mountains/{slug}/pressure-points`.
- [ ] **27.** Trace a runout from a pressure point. `backend/app/ml/runout.py`.
- [ ] **28.** Expose simulate, the stream, and the callouts.
- [ ] **29.** Open the mountain panel over the globe.
- [ ] **30.** Play the simulation in the panel.
- [x] **31.** Finish the hill card. Trail scores, markers, the overall score, mean slope, and preventative measures now come from `GET /mountains/{slug}/trail-risk`. `frontend/lib/fixtures/hill-demo.ts` is only the fallback when that endpoint does not answer.
- [ ] **ML: Model B saturates.** With the trained susceptibility (median 0.000, mean 0.058), the storm fixture puts 100% of the map at extreme and a dry week puts all of it at low, because the terrain term is centered at 0.5 and moves the logit by at most ±1.2 while rain moves it by ±3.6. The heat map then has no spatial pattern and Skyline is flagged end to end, so no bypass exists. A log-odds form (`logit(susceptibility) + w2·rain + w3·moisture`) keeps the terrain pattern (storm: 11% extreme) but never flags Skyline. The ML track decides.

## Before the demo

- [ ] Provision hosted Postgres, set `DATABASE_URL`, then run `python -m app.schema && python -m app.seed` from `backend/`.
- [ ] Set `GEMINI_API_KEY` and `XAI_API_KEY`. Run `python -m app.agents.pipeline` once, then one **Analyze now** in the browser. Without a key, **Analyze now** answers 503 and says which key to set. `curl 'localhost:8000/health?verbose=1'` shows which keys are present.
- [ ] Keep `OPEN_METEO_FALLBACK_FIXTURE` set, so a venue network that blocks Open-Meteo still runs (on the last good response first, then the storm fixture, each labeled).
- [ ] Rehearse the demo script in [TerraSense.md](TerraSense.md) three times. Keep one finished run on screen as a fallback.
- [ ] After the merge, write the measured AUC (0.715 on that branch) into the Devpost draft.

## Catalog

- [ ] The globe target is about 1,000 peaks. `data/seed/mountains.json` has 648 (`SEED_MODE=reseed`). The default `SEED_MODE=mountainstest` loads 138 peaks from `data/seed/mountains_test.json`, and the globe draws 50 unless `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` changes. Re-run `python -m app.mountain_catalog --write-seed` from `backend/` only if the demo needs the full set.
