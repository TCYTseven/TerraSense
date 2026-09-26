# Pending — Saturday, Sep 26, 2026

Open work only. Build notes stay in [implementation-steps.md](implementation-steps.md).

## Merge

- [ ] Merge `origin/step-10-local-nasa-export` into main. It holds steps 10, 11, 12, 14, and 17. Main does not. Do not rebuild them. The branch is 7 commits ahead of `7ca0f8d`; main is 6 commits ahead of that same point (catalog, live **Analyze now**).
  - **10.** `data/seed/landslides.geojson`: 4 NASA events and 33 Washington inventory labels.
  - **11.** Labeled feature table, 1,224 rows, on the 30 m stack.
  - **12.** LightGBM trained. Held-out spatial AUC 0.715, since replaced by the regional model (0.82 spatial CV, 0.60 on Rainier). Susceptibility tiles rendered.
  - **14.** 37 historical pins. The 67 trails and 55 Skyline segments are already on main.
  - **17.** `backend/app/ml/model_b.py`: susceptibility plus forecast rain and antecedent moisture.

## Build

- [x] **26.** Rank the pressure points. `backend/app/ml/pressure.py` and `GET /mountains/{slug}/pressure-points`.
- [x] **27.** Trace a runout from a pressure point. `backend/app/ml/runout.py`.
- [x] **28.** Expose simulate, the stream, and the callouts.
- [ ] **29.** Open the mountain panel over the globe.
- [x] **30.** Play the simulation on the mountain page, beside **Analyze now**, for mountains with routes.
- [ ] **31.** Finish the mountain page. Agents, Reactive Measures, trail scores and markers, the overall score, mean slope, and preventative measures now come from the API (`GET /mountains/{slug}/risk-summary`). Left: check the five trails against the advisory after a fake-LLM run.
- [x] **36.** Rename the mountain page off the word hill.
- [x] **37.** Record hills in the spec. First hill: Turtle Mountain, Crowsnest Pass, Alberta (`turtle-mountain`).
- [x] **38.** Seed and serve Turtle Mountain (`kind`, `data/seed/hills.json`, `GET /hills/{slug}`).
- [ ] **39.** Score Turtle Mountain with the existing landslide model on its own terrain window.
- [ ] **40.** Hill glyph, fly-to, and hill page. Agents stay idle.

## Before the demo

- [ ] Provision hosted Postgres, set `DATABASE_URL`, then run `python -m app.schema && python -m app.seed` from `backend/`.
- [ ] Set `GEMINI_API_KEY` and `XAI_API_KEY`. Run `python -m app.agents.pipeline` once, then one **Analyze now** in the browser.
- [ ] Rehearse the demo script in [TerraSense.md](TerraSense.md) three times. Keep one finished run on screen as a fallback.
- [ ] Write the validated numbers into the Devpost draft: terrain ROC-AUC 0.82 (0.78–0.85) regional, 0.60 (0.52–0.67) on Rainier; rain trigger 0.75 (0.73–0.78).

## Catalog

- [ ] The globe target is about 1,000 peaks. `data/seed/mountains.json` has 648 (`SEED_MODE=reseed`). The default `SEED_MODE=mountainstest` loads 138 peaks from `data/seed/mountains_test.json`, and the globe draws 50 unless `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` changes. Re-run `python -m app.mountain_catalog --write-seed` from `backend/` only if the demo needs the full set.
