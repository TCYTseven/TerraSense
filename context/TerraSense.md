# TerraSense

> Landslide hazard intelligence for hikers and park rangers, built on satellite terrain data.

HackGT scope. This document is the build target. If a feature is not in [Hackathon scope](#hackathon-scope), do not build it.

---

## Table of Contents

1. [One-Liner](#one-liner)
2. [Where the Build Stands](#where-the-build-stands)
3. [Hackathon Scope](#hackathon-scope)
4. [The Problem](#the-problem)
5. [What TerraSense Does](#what-terrasense-does)
6. [Who It Is For](#who-it-is-for)
7. [Core Features](#core-features)
8. [User Flows](#user-flows)
9. [System Architecture](#system-architecture)
10. [Data Sources](#data-sources)
11. [ML Pipeline](#ml-pipeline)
12. [Agent Design](#agent-design)
13. [Tech Stack](#tech-stack)
14. [Design Language](#design-language)
15. [Data Model](#data-model)
16. [API Surface](#api-surface)
17. [Build Plan](#build-plan)
18. [Demo Script](#demo-script)
19. [Devpost Write-Up Draft](#devpost-write-up-draft)
20. [Risks](#risks)
21. [Out of Scope](#out-of-scope)
22. [Decision Log](#decision-log)
23. [Glossary](#glossary)

---

## One-Liner

TerraSense reads terrain and weather for a mountain, predicts where a landslide is likely in the next 72 hours, and turns that into two outputs: an alert a park ranger can act on, and a plain-language forecast that tells a hiker which trail segment to skip.

---

## Where the Build Stands

As of Saturday, Sep 26, 2026. [implementation-steps.md](implementation-steps.md) splits the steps into done and pending. Open work is [9-26-todo.md](9-26-todo.md).

**Works end to end**

- **Globe.** A React Three Fiber Earth on the light home theme, evenly lit so no side goes black. Mountain-logo markers come from the API. The default seed (`SEED_MODE=mountainstest`) is 138 peaks, and the globe draws 50 unless `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` changes. Mount Rainier is the only live mountain. High and Extreme mountains sit in a larger translucent sphere. Hover cards, search, and a 1.5 s fly-in to `/mountains/[slug]`.
- **Mountain page.** Two columns, rebuilt Sep 25:
  - **Map, about 55%.** MapLibre GL with 3D terrain from AWS Terrain Tiles. The mountain renders gray on white surroundings. The opening frame is sized from the summit elevation, so any mountain opens the same way. The camera slowly orbits while idle, and zooming out stops one level past the opening view. The heat map is the default layer, with a susceptibility toggle. All 67 OpenStreetMap trails are drawn, and the hero trail (the Skyline loop, 5.5 mi) is colored by 0.1-mile segment. Five lettered markers (A–E) sit on the top at-risk trails, each with a hover tooltip (score, slope, primary factor), and **View** flies the camera to them.
  - **Panel, about 45%.** Stats, the overall score, the top five trails, preventative measures, an Orchestrator with five agent cards and inline reasoning traces, **Analyze now**, and a Reactive Measures section clustered by timing (now, within 1 hour, 6 hours, 24 hours).
- **Assessment.** `backend/app/assessment.py` scores the map, colors the hero trail's 55 segments, flags the worst mile range, draws the hazard zone around it, and routes a bypass on the OpenStreetMap trail network, or says to turn back. `backend/app/trailscan.py` scores every mapped trail against the same map.
- **Agents (backend).** **Analyze now** (`POST /mountains/{slug}/analyze`) runs seven agents and streams them over a WebSocket:
  - five analysts in parallel: Terrain, Weather, Trail, History, and Route Scout;
  - then the Risk Synthesizer, which decides the severity, the action, three routes to avoid, three safe routes, and the ranger response, with guard rails in `advisory.py`;
  - then the Alert Writer.

  A router sends each call to Gemini Flash or Grok and records why. The run's conclusion is served as an advisory (`GET /runs/{id}/advisory`, `GET /mountains/{slug}/advisory`).
- **Weather.** Open-Meteo precipitation drives the model. Temperature, freeze-thaw, snowfall, wind, soil moisture, and the freezing level are context for the agents, and missing readings stay null.
- **Tests.** 240 pytest tests pass against a fake of both LLM APIs (`backend/tests/fake_llm.py`), including contract tests for the Model B seam, the provider schemas, and every payload that leaves the process.

**Not done yet**

- **The mountain page is nearly wired.** On Mount Rainier, **Analyze now** streams the seven agents into the five cards (Trail, History, and Route Scout share the Trails row) and Reactive Measures come from the advisory (`frontend/lib/pipeline/live-run.ts`). Trail scores, markers, the overall score, mean slope, and preventative measures come from `GET /mountains/{slug}/risk-summary`, which scores every trail on the saved map the heat layer shows (`backend/app/risk_summary.py`). Left: check with the fake LLM server that the five trails match the advisory after a run.
- **The hiker card and the hazard block** are not rendered since the rebuild. Their components are kept.
- **Static mountains** (Huascarán, Mount Fuji) open the card with their level only.
- **Landslide points.** The supplied NASA Global Landslide Catalog export contributes 4 Rainier events; because only one is `1km` accurate, the downloader adds 33 documented Washington Geological Survey inventory points as supplemental training labels. The **Past landslides** toggle is enabled, and the History Analyst can read all 37 records.
- **LightGBM (regional, Sep 26).** Trained on 7,351 Washington Geological Survey landslide pixels across the western Cascades, with the Rainier box and a 2 km buffer never in training. ROC-AUC `0.82` (95% CI 0.78–0.85) over 5 spatial folds of 10 km blocks, isotonic-calibrated (ECE 0.026). On the Rainier box's own 93 mapped slides it is `0.60` (0.52–0.67): weak, and published as such. Scores are relative susceptibility, because negatives were sampled 1:3. See `ml/artifacts/metrics.json`. The superseded Rainier-only run (AUC 0.715, seven features) is no longer kept as a separate artifact tree.
- **Model B validation (Sep 26).** Case-crossover on 767 dated Pacific Northwest landslides (416 storms, 1980–2023) against same-place quiet days, with ERA5 rain (`ml/scripts/event_validate.py`). ROC-AUC `0.75` (0.73–0.78) with whole water years held out, ECE 0.032. See `ml/artifacts/model_b_validation.json`.
- **Model B (step 17)** is live. `backend/app/ml/probability.py` calls `backend/app/ml/model_b.py`, which combines the trained susceptibility raster with bounded forecast-rain and antecedent-moisture signals.
- **Local ML artifacts.** A machine without `ml/artifacts/susceptibility.tif` fails a run before scoring. `/health` and the run's error name the missing file and the commands that build it.
- **Mountain page simulation** (6.8). **Simulate** sits beside **Analyze now** on mountains that have routes. It flies to the route most likely to fail and plays an illustrative debris-flow runout, with a time bar on the mountain view kept in step with the flow. The centered globe panel from the Sep 25 decision is still not built.
- **Live providers and hosting.** No live Gemini or xAI call has run, and no hosted Postgres is provisioned. Rehearse once with real keys before the demo.
- **Catalog size.** `data/seed/mountains.json` has 648 peaks. The written target is about 1,000. The default seed is the 138-peak test file.
- **Hills.** Specified Sep 26. Turtle Mountain is the first hill and is not seeded yet. The hill glyph and `/hills/[slug]` are not built.

Example copy in this file ("Ridge Trail mile 4.2 to 5.1", "Cedar Loop") is illustrative. The live trail is the Skyline loop, and the bypass comes from the trail network.

---

## Hackathon Scope

Build one convincing loop, not a platform.

**In**

- A 3D globe. Click Mount Rainier and fly in. One hill marker, Turtle Mountain in the Crowsnest Pass, uses a hill glyph and opens a hill page.
- Two extra mountains as static globe markers so the globe is not a single dot. They do not run live analysis.
- One live mountain: **Mount Rainier**. Precompute its terrain features before the event. Rainier stays the demo mountain on the existing landslide model; the separate avalanche classifier is an API/offline follow-on and does not change the landslide score.
- One live hill: **Turtle Mountain**, Crowsnest Pass, Alberta. The existing regional LightGBM and Model B score it. Agent orchestration is not on the hill page.
- Landslide risk remains the primary demo hazard: a static susceptibility layer and a 72-hour probability layer driven by recent rain.
- Historical landslide pins from a public catalog.
- Trails colored by risk, plus one alternate route that avoids the worst segment.
- Agents that stream their work into the UI: five analysts, a Risk Synthesizer, and an Alert Writer.
- The ranger alert in the app, with each agent's reasoning trace inline and Reactive Measures grouped for an incident response.
- A hiker forecast card in plain language.
- A mountain-page runout for any peak that has routes: **Simulate** beside **Analyze now**, a debris-flow footprint down the worst route, and a time bar locked to that footprint (team decision, Sep 26, 2026). See [6.8](#68-mountain-page-runout). The Sep 25 globe panel remains specified and is not built.

**Out**

See [Out of Scope](#out-of-scope). The short version: no rain what-if inputs, no extra hazard types (the simulation is landslide and debris flow runout only; a snow avalanche needs a snowpack this model does not have), no SMS or email (public notices are drafts), no accounts, no GPX export, no InSAR.

**Demo proof**

A judge can spin the globe, open Mount Rainier, press **Simulate** beside **Analyze now**, and watch a debris flow run downhill while the time bar on the mountain view stays in step with it. Then they see the five at-risk trails, watch the agents run, open their reasoning, and read the Reactive Measures.

---

## The Problem

Hikers check the weather before they leave. Almost nobody checks whether the slope above the trail has taken days of rain and is close to failing.

Use these numbers only after you source them. They are placeholders:

- The USGS estimates landslides cause 25 to 50 deaths and on the order of $1 billion to $2 billion in damage in the US each year.
- Rainfall-triggered shallow landslides and debris flows are the events most likely to hit trails. The trigger is rainfall, which weather APIs already publish.
- A ranger district covers too much ground to inspect every slope after every storm.

The data already exists: elevation models, land cover, precipitation, and landslide inventories. It sits in formats built for geoscientists. NASA's LHASA model already nowcasts landslide hazard globally. LHASA does not say "close Ridge Trail between mile 4.2 and 5.1, use the Cedar Loop." TerraSense is that last mile.

---

## What TerraSense Does

1. **Ingest.** Use a preprocessed terrain stack for Mount Rainier, plus a live precipitation forecast.
2. **Predict.** Score each terrain cell for long-term landslide susceptibility, then for short-term probability given recent and forecast rain.
3. **Decide.** Five analyst agents read the scores, the weather, the trails, and the landslide record; a Risk Synthesizer decides the severity, the routes, and the ranger response; an Alert Writer turns it into sentences a person can act on.
4. **Deliver.** Show it on a 3D globe and a terrain map. Give the ranger the alert in the side panel. Show the hiker a forecast card and a bypass.

The output is a label, not a chart. Example: "Trail closed between mile 4.2 and 5.1. Debris flow risk high. Use the Cedar Loop bypass."

---

## Who It Is For

**Park rangers.** They need to know which trail segment to close after a storm, and why.

**Hikers.** They need a five-second answer: is this trail safe today, and what should I do instead.

Search and rescue, event organizers, and insurers are not users for this build.

---

## Core Features

### 6.1 The 3D Globe

The first screen is a full-screen 3D Earth.

- React Three Fiber, Three.js, and drei. A custom globe (`frontend/components/globe/`), not a globe library.
- Textured Earth (`earth-day.jpg` with a topology bump map), evenly lit on the light home theme, and a light atmospheric rim.
- Markers are a mountain logo or, for a hill, a single rounded rise with no snowcap. Color encodes overall risk on all four levels (see the design addendum's Risk mapping); High and Extreme places also sit in a larger translucent sphere of that color. Rainier is live and gets an extra ring. Turtle Mountain is the one live hill. The other markers use a fixed risk value loaded from seed data.
- Drag, zoom, and a slow idle rotation that pauses on hover and during a flight.
- Hover shows mountain name, elevation, region, risk level, and last refresh time.
- A mountain click turns the globe to face the mountain and opens the mountain panel (6.8). **Open ranger view** in the panel flies the camera in over 1.5 s, fades to the background, and opens the mountain view. (Built today: the click flies straight in to `/mountains/[slug]`. Steps 29 and 30 move it behind the panel.) A hill click uses the same fly-to and opens `/hills/[slug]`.
- A search box accepts "Mount Rainier" (or "mt rainier") and "Turtle Mountain", and opens the matching place.

The globe is the demo hook. Keep it small and fast. Three markers is enough.

### 6.2 Mountain View

Clicking Rainier opens a MapLibre GL map (the open-source fork of Mapbox GL) with 3D terrain (exaggeration about 1.5) and a light shaded relief. With a Mapbox token it shows Mapbox satellite imagery instead.

**Layers**

- **72-hour landslide probability.** The live heat map. This layer is on by default. It fades in over 600 ms. Until Model B lands, it is the susceptibility stand-in, labeled as such.
- **Susceptibility.** The static "this slope can fail" layer. One toggle. While it is on, the probability layer is hidden.
- **Trails.** Lines from a pre-downloaded OpenStreetMap extract. The hero trail is colored by segment risk, and the other trails are thin and neutral.
- **Historical events.** Pins from the landslide inventory. The toggle is disabled until the catalog points exist.
- **Hazard pin.** One primary pin on the flagged zone. Clicking it opens the detail block.

**Hazard detail**

Four fields, always in this order:

1. What it is.
2. Why the model flagged it.
3. Confidence.
4. How to avoid it.

**Mountain page** (rebuilt Sep 25, 2026)

The page is two columns: the 3D mountain view about 55%, one scrolling stats panel about 45%. Each of the top five trails gets a letter marker (A to E) on its region; hovering one shows its risk score, slope, and primary risk factor. The panel, top to bottom:

- Mountain name and one line of stats: elevation, mean slope, area.
- Overall risk: the score as a number, with the level word and color.
- Top 5 at-risk trails, riskiest first: letter, name, score, and **View**, which flies the camera to the trail's region.
- Preventative measures: three to five bullets.
- The agent pipeline: an Orchestrator node connected to Terrain, Weather, Trails, Synthesizer, and Mass Alert Writer cards. A click on a card opens its reasoning trace beneath it. After a run, **Reactive Measures** appear below as a prominent section, clustered by when each has to happen (now, within 1 hour, 6 hours, 24 hours). Each measure is labeled with its kind of work: closures and access, evacuation and sweeps, search and rescue readiness, field monitoring, agency coordination, or a public notice draft.
- Button: **Analyze now**, pinned to the panel bottom.

There is no rain section. Weather is text in the Weather agent's trace, never a map layer. On Mount Rainier the trail scores, overall score, and mean slope come from the saved 72-hour map, and the traces and measures from a live run. Static mountains still use the scripted client-side orchestrator.

**Hill page.** `/hills/turtle-mountain` reuses this layout. Prevention shows the heat map's scores. Response shows the five agent cards idle, and **Analyze now** is absent. The hill has no trails until some are imported, so **Simulate** stays off.

### 6.3 Landslide Model

Two stages. Both stay explainable.

**Model A, susceptibility (offline)**

- One row per pixel on a 30 m UTM grid: slope, aspect, curvature, elevation, distance to drainage, land cover, topographic wetness index.
- Label: landslide inventory point, buffered 50 m, versus sampled stable terrain at about 1:3.
- Model: LightGBM binary classifier.
- Split by space (7.5 km region blocks), not by random row, so neighboring pixels do not leak into the test set.
- Output: susceptibility from 0 to 1, saved as a raster before the demo.
- Record AUC and precision at the High threshold. Publish the number you get. Do not treat 0.85 as a gate.
- **Current state.** The trained artifact and model card are present in `ml/artifacts/`; the knowledge-driven index remains a deterministic fallback when the labeled table is unavailable.

**Model B, triggering (live)**

- Inputs: Model A score, 3-day and 7-day precipitation from Open-Meteo, and forecast rain over the next 72 hours.
- Method: a rainfall intensity-duration threshold (Guzzetti-style) plus an antecedent moisture index from recent rain, blended with susceptibility:

`index = sigmoid((logit(susceptibility) − logit(0.25)) + w0 + w2 · rainfall_exceedance + w3 · moisture_index)`

- Tune weights on the dated events you actually have. If that set is tiny, say so and keep the weights explicit.
- Categories: Low < 0.2, Moderate 0.2–0.45, High 0.45–0.7, Extreme > 0.7. Adjust so Rainier shows a visible High zone for the demo, and document the adjustment.
- **Current state.** `backend/app/ml/probability.py` is the one seam and calls `model_b.run(rain)`. Dry, missing-rain, and storm paths are covered by contract tests; the result is a float32 0–1 raster with the susceptibility grid's transform and CRS.
- **Weights (Sep 26, fitted).** Terrain enters as the log-odds of the calibrated susceptibility relative to its 1:3 sampling rate (`logit(0.25)`), so the index carries one base rate, `w0`'s. `w0 = -1.32`, `w2 = 0.92`, `w3 = 0.76` are the logistic fit on the 767 dated events, with 95% CIs -1.51 to -1.18, 0.74 to 1.10, and 0.59 to 0.93. The earlier hand-set `w2 = 2.0` and `w3 = 1.6` were outside those intervals. The fit ranks days 0.005 worse by ROC-AUC (95% CI −0.007 to −0.002, so `weights_published` stays `false` in the artifact) but cuts calibration error from 0.189 to 0.032. The index is binned into the shared levels, so calibration won. Terrain and rain were each validated; their product assumes they act independently and was never validated as a whole, because no dated event cell falls in the Rainier box. The absolute level depends on the sampling ratios, so the output is a relative 72-hour risk index, not a probability. A dry week leaves 99% of the box Low. Rain at both thresholds leaves 67% Low and 3.5% High. The storm fixture puts 47% at High or above and flags Skyline miles 4.1 to 5.4, a run the trail network cannot route around, so that storm has no bypass. On Rainier's own slides, slope alone (ROC-AUC 0.64) ranks better than the terrain model (0.60); the card shows both.
- **Point probability.** `POST /api/v1/landslide-risk` answers every in-domain click with `probability`: the Model B value at that pixel, labeled `model_b_estimate` and explained by its three logit terms, until a calibrated classifier replaces it. See [docs/production-risk.md](docs/production-risk.md).
- **Hills (Sep 26, 2026).** This LightGBM plus Model B is the hill model. Turtle Mountain gets its own DEM and land-cover window; the Washington training raster does not cover Alberta, and a placeholder terrain sample is not an answer. The published scores stay the Washington figures: spatial-block ROC-AUC 0.82, and 0.60 on Rainier's own slides. Those numbers are not Turtle Mountain's accuracy. The Frank Slide of 29 April 1903 was a rockslide, so Model B's rain trigger is not an explanation of that event. Rainier remains the demo mountain on this same code until a separate mountain model exists. That model is not started.

Feature importance from LightGBM is enough for the "why" sentence. Skip SHAP.

### 6.4 Agents

Seven LLM calls with separate prompts. Every agent reads the ML model's prediction first and explains it; none argues with it.

| Agent | Job | Output |
|---|---|---|
| Terrain Analyst | Describes the worst cluster on the probability raster | One hazard zone: type, severity, drivers, confidence |
| Weather Analyst | Says whether the next 24–72 hours make that zone worse, stable, or better | A modifier and a short weather note |
| Trail Analyst | Explains which hero-trail miles cross the zone and the bypass the code found | Affected mile range, bypass, severity |
| History Analyst | Says whether the landslide record supports today's rating (an empty record is not evidence of safety) | Precedent, severity, note |
| Route Scout | Reads every mapped trail and names the most exposed and the clearest | Exposed and clear trails, network severity |
| Risk Synthesizer | Decides what the park does today | Final level, action, three routes to avoid, three safe routes, ranger response |
| Alert Writer | Writes the ranger alert and the hiker text | Two short texts |

The five analysts run in parallel, then the Risk Synthesizer, then the Alert Writer. Each result streams to the UI. Code sets the final confidence (weights: terrain 0.30, weather 0.25, trail 0.20, routes 0.15, history 0.10) and checks the Synthesizer's routes and posture (`advisory.py`).

The mountain page shows five cards: Terrain, Weather, and Trails together, then the Synthesizer, then the Mass Alert Writer (the card's name for the Alert Writer). On a live mountain those cards follow the API. History and Route Scout fold into the Trails row. Static mountains still use the scripted source.

Consensus rule: if severity ratings differ by two or more levels, set `needs_review` and phrase the alert as an advisory.

### 6.5 Ranger Alert

The alert stays in the app. When a run finishes, the hazard pin opens and the panel shows the four fields: what it is, why it was flagged, confidence, and how to avoid it. The Mass Alert Writer card's trace holds the ranger title and paragraph and the Synthesizer's recommended action (monitor or close).

Discord was dropped on Sep 25, 2026 (team decision). There is no ranger account, no inbox, and no acknowledge button.

### 6.6 Hiker Forecast

A card, not a second product.

- Trail name, today's level (Low / Moderate / High / Extreme), and one sentence.
- The bypass: name, added distance, added elevation.
- The same bypass drawn on the mountain map, dashed.

The Alert Writer produces the sentence. The bypass values come from the API, never from the model's text. No account, no share image, no file download.

Not rendered on the rebuilt mountain page for now (UX.md, Mountain page); `GET /forecast` and the component are kept.

### 6.7 Reasoning Panel

Added Sep 25, 2026 (team decision); folded into the mountain page the same day. The reasoning now opens inline: a click on an agent card expands its full trace directly beneath it, one card at a time. It updates live during a run. It explains a run and never changes one. The side panel over the map is gone.

### 6.8 Mountain page runout

Added Sep 25, 2026 as a panel over the globe. Moved onto the mountain page on Sep 26, 2026: **Simulate** belongs beside **Analyze now**, and only a mountain with routes gets it. Mount Rainier is the only seeded peak with routes. Peaks without routes do not show the button.

**Simulate.** The simulation runs only on the one route most likely to fail, never on another route or pressure point. That route has the highest probability-map value anywhere along its line when the raster exists, and otherwise it is the steepest route in the trail catalog (climb per kilometer). The camera flies to it. The map then plays an illustrative landslide and debris-flow runout:

- **Runout.** The flow is an area on the terrain, not a line. It releases from a small patch at the route's highest point and spreads over a 26 m elevation grid built from the same Terrarium tiles as the map's terrain (Sep 26, 2026). Holmgren multiple-flow-direction routing (`HOLMGREN_EXPONENT` 1.1, the diffuse end, so it fans across open slopes) passes each cell's share only to lower neighbors, so the flow never runs uphill. It stops where the travel angle from the release drops below `REACH_ANGLE_DEG` (11°), at a pit, or past `MAX_RUNOUT_M`. The body widens downhill: margins one cell wide at the release, one more every 300 m up to four, each no higher than the cell it grows from. Arrival time is path distance divided by `FRONT_SPEED_MS` (5 m/s). Frames are polygons of the cells reached by each time. If no terrain tile can be read, the footprint falls back to a band along the route from its highest point. On the map the footprint is dirt on the ground: dark brown in its interior, paling to light brown at its edges, so it starts brown at the release and grows lighter sides as it spreads. It is not a snow avalanche: there is no snowpack to drive one.
- **Heat on the map.** The footprint advances frame by frame on the risk ramp, hotter in the core and cooler at the edges. The existing heat map drops to 35% opacity while the flow shows. One frame every 500 ms, at most 40 frames.
- **Time bar.** A bar across the top of the mountain view shows the simulated span and the current clock (`T+04:30`). The playhead and the footprint move together. The bar does not scrub, and there is no rain slider, speed control, or hazard picker.
- **Steps and callouts.** Code names the release, the channel, each trail the flow reaches (name and mile range), and the stop. Callouts are drafts for rangers and for the public. Nothing is sent. When the model does not answer, templates stand in and the finished line says so.
- **Replay.** Runs the frames already loaded. The method line stays on screen: the runout is illustrative, not a forecast of timing.

**Open ranger view** on the still-unbuilt globe panel would fly into this same page. Static mountains, and any mountain with no routes, have no **Simulate**.

It is labeled as an illustrative runout, not a forecast of timing. Avalanches stay out.

---

## User Flows

### Ranger alert

1. The demo starts from **Analyze now** (a scheduled overnight job is out of scope).
2. The run fetches rain once, scores the map (Model B, or the stand-in), and reassesses the hero trail, hazard zone, and bypass.
3. Terrain and Weather run together. Trail Analyst names the affected segment and explains the bypass. The Synthesizer sets the level or flags `needs_review`. Alert Writer drafts both texts.
4. The run finishes. In one transaction the API renders new probability tiles, stores segment risk, and saves the hazard. The pin opens on the new heat map with the four-field panel.
5. **Reasoning** shows which model each agent ran on, why the router picked it, and what the agent read.

### Hiker check

1. Open the globe, click Mount Rainier.
2. Open **Hiker forecast** for the flagged trail.
3. Read the level, the sentence, and the bypass (added distance and elevation) on the map.

### Judge demo

1. Land on the rotating globe.
2. Open Mount Rainier.
3. Press **Simulate**, beside **Analyze now**. Watch the flow reach the valley in step with the time bar, and read the callouts. **Replay** if needed.
4. Show the probability heat map, then toggle susceptibility and historical pins.
5. Click **Analyze now**. The agent rows fill in.
6. Open a card's trace.
7. Read the Reactive Measures.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     FRONTEND (Next.js)                      │
│   3D Globe (R3F) → Mountain panel + simulation              │
│   → Mountain map (MapLibre) → Hiker card                    │
│   Ranger panel + reasoning panel                            │
│              WebSocket (agent stream)    REST               │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                    API (FastAPI)                            │
│   /mountains /layers /analyze /runs /forecast               │
│   /pressure-points /simulate /simulations                   │
│   in-process run registry, WebSocket relay, /tiles          │
└────────────┬───────────────────────┬───────────────────────┘
             │                       │
   ┌─────────▼──────────┐   ┌────────▼──────────────────┐
   │  ML (Python)       │   │  5 agents                 │
   │  probability seam, │   │  router → Gemini Flash    │
   │  hazard zone,      │   │           or Grok         │
   │  bypass, tiler     │   │  tools return facts only  │
   └─────────┬──────────┘   └────────┬──────────────────┘
             │                       │
   ┌─────────▼───────────────────────▼─────────┐
   │  Postgres: mountains, trails, segments,    │
   │  runs, hazards. GeoJSON stored as JSON.    │
   │  Rasters and XYZ tiles on disk.            │
   └────────────────────────────────────────────┘
             ▲
   ┌─────────┴──────────────────────────────────┐
   │  Before the event: DEM, land cover, trails,│
   │  trail network, landslide points.          │
   │  Live: Open-Meteo only.                    │
   └────────────────────────────────────────────┘
```

Keep the API thin. Model B and the agents run in the same Python service. Move inference to Modal only if a local run is too slow or the laptop fans become the demo.

Serve map tiles from the app (`/tiles`). One mountain does not need object storage.

Store agent state in the API process, keyed by `run_id`. One demo mountain does not need Redis. A finished run is also stored on its `analysis_runs` row, so it survives a restart.

---

## Data Sources

Download and clip these before the event. Everything is for Mount Rainier unless noted. `data/seed/sources.md` has the URLs, access dates, licences, and checks.

| Data | Source | Use | Status |
|---|---|---|---|
| Elevation | Copernicus DEM GLO-30 | Slope, aspect, curvature, wetness index, bypass climb | Done |
| Land cover | ESA WorldCover 2021 | Model A feature | Done |
| Landslide points | NASA Global Landslide Catalog plus a documented Washington state inventory supplement | Model A labels and map pins | Supplied NASA export used; sparse high-accuracy events are supplemented for spatial training |
| Precipitation | Open-Meteo, downscaled to Paradise (1,650 m) | Model B, live | Done. `OPEN_METEO_FIXTURE` loads a synthetic storm offline |
| Trails | OpenStreetMap, via Overture Maps (release 2026-09-23.0) | Trail risk and the bypass | Done: 67 trails, the Skyline loop in 55 segments, a 114-edge network |
| Basemap | AWS Terrain Tiles (elevation, shaded relief). Mapbox satellite when a token is set | Mountain view | Done |

The other two globe markers need a name, a coordinate, and a static risk level. They do not need rasters.

---

## ML Pipeline

### Before the event

1. Clip a DEM to a Rainier bounding box. (`download_sources.py`, step 10)
2. Build slope, aspect, curvature, topographic wetness index, and distance to drainage (D8 channels via pysheds) with rasterio. (`build_features.py`, step 11)
3. Resample land cover to the same 30 m grid, mode resampled.
4. Buffer inventory points to about 50 m for positives. Sample negatives from the rest of the box at roughly 1:3.
5. Save a feature table and the susceptibility raster. (`train_susceptibility.py`, step 12)
6. Save trail lines as GeoJSON, split into segments with mile markers you can explain on stage, plus the walkable network the bypass routes on. (`import_trails.py`, `build_trail_network.py`)

### At the event

1. Train LightGBM if you did not finish training beforehand. Spatial split: hold out one part of the box, or a nearby area, as the test set.
2. Write the Model B function so it only needs the cached susceptibility raster and an Open-Meteo response.
3. Turn the probability raster into XYZ tiles in Web Mercator (EPSG:3857) so the map lines up with the terrain. The shared tiler renders 383 tiles in about 3 s.
4. Extract the flagged zone as one polygon for the hazard pin: the high cells within 250 m of the hero trail's worst miles.

Target: Model B plus tiling finishes in under 30 seconds. Scoring takes about 0.4 s today and publishing about 3 s.

---

## Agent Design

Each agent is a function that receives the run context, calls one model with a fixed prompt, and returns JSON validated with Pydantic. The API stores that JSON on the run and pushes it down the WebSocket as an `AgentEvent` with a trace.

**Models and the router**

- Terrain, Weather, and Trail start on the fast model: Gemini Flash.
- Synthesizer and Alert Writer start on the stronger model: Grok. These two judge and write.
- A router in code (`backend/app/agents/router.py`, team decision Sep 25, 2026) picks one provider per call and records every rule it checked:
  - It escalates a borderline fast task to Grok: a zone peak within 0.05 of a bin edge, rain within a third of the 72-hour threshold, or a missing or risky bypass.
  - It moves a clear, low-stakes strong task down to Gemini: three reports agreeing at moderate or below, or a routine monitor notice.
  - Past 42 s of the 60 s budget, it moves Grok calls to Gemini.
  - It rests a provider that is missing a key, or that failed twice in two minutes, and falls back to the other one.
  - Either key alone works, and `LLM_ROUTER` forces one provider.
- Each call gets two tries per provider: a retry after a temporary failure, or a repair round after a failed check. Then it moves to the fallback provider. When the Writer keeps failing its copy checks, plain templates replace its text.

**Tools**

- `get_raster_summary(mountain_id)` returns the map summary, its method, and the hazard zone with the terrain under it. The agent does not scan pixels.
- `get_trail_segments(mountain_id)` returns risk by mile, the flagged miles, and the bypass or the turn-back advice.
- `get_weather(lat, lon)` returns rain totals, Guzzetti thresholds and ratios, and a warning when the rain comes from the fixture.
- `get_historical_events(lat, lon, radius_km)` lets the Terrain or Synthesizer note mention a past debris flow without a sixth agent.

The bypass is computed in Python on the trail network: for each detour, the walking added plus the trail given up, with each meter at high or above counting four times. The Trail Analyst explains that result. It does not invent geometry.

**Terrain Analyst shape**

```json
{
  "hazard_zone": {
    "id": "hz_001",
    "type": "debris_flow",
    "severity": "high",
    "max_probability": 0.71,
    "drivers": ["slope_angle", "drainage_proximity", "recent_rain"],
    "confidence": 0.84,
    "notes": "Cluster on the east fork, steep slopes, sparse vegetation."
  }
}
```

**Confidence**

```
final_confidence = Σ (agent_confidence_i · agent_weight_i) / Σ agent_weight_i
```

Weights are constants in code (`CONFIDENCE_WEIGHTS`: 0.40, 0.35, 0.25). If two severity labels differ by two levels, set `needs_review`.

Target: the five calls finish in about a minute. Cap each output at a short JSON object plus a few sentences.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript |
| UI | Tailwind CSS 4, tokens named for shadcn/ui |
| Globe | React Three Fiber + Three.js + drei |
| Map | MapLibre GL JS with 3D terrain from AWS Terrain Tiles. No key needed |
| Realtime | FastAPI WebSocket |
| API and agents | FastAPI, Pydantic, httpx, psycopg 3 |
| ML | LightGBM, rasterio, pysheds, Shapely, networkx |
| Database | Postgres (Neon or Supabase). Geometries as GeoJSON |
| LLMs | Gemini Flash and Grok, picked per call by a router in code. Either key alone works |
| Tests | pytest with a fake Gemini and xAI server |
| Deploy | Vercel for the frontend. API on Railway, Modal, or a laptop tunnel |

Skip auth, Redis, PostGIS, object storage, Docker-as-a-requirement, Twilio, and email for this build.

---

## Design Language

Dark and operational, like a small dispatch screen. The hiker card is the only softer surface. [design-addendum.md](design-addendum.md) turns these tokens into component rules.

**Color**

- Background `#0D0C0A` to `#13120F`.
- Panels `#1A1814`, 1 px border at about 10% of the text color.
- Interactive accent `#7FDDE6`.
- Risk only: green `#22C55E`, amber `#F59E0B`, orange `#F97316`, red `#EF4444`.
- Text `#ECE6DC`, muted `#9C9387`.

**Type**

- UI: Inter, Geist, or Space Grotesk. The build currently loads Geist.
- Coordinates, times, and scores: JetBrains Mono or Geist Mono. The build currently loads Geist Mono.

**Layout**

- Globe: full bleed. Name at the top left, search in the center.
- Mountain: map about 70% width, panel about 30%. Layer toggles as a small group over the map.
- Agents: one row each, with a status (waiting, running, done) and the latest line.
- Hiker card: larger type, same dark background.

**Motion**

- Idle globe rotation. Fly-to in about 1.5 seconds.
- Heat map fades in.
- The running agent row pulses.
- A High or Extreme alert is visually distinct in the panel.

**Copy**

- Ranger text is short. "Debris flow risk HIGH. East fork drainage. Confidence 0.82."
- Hiker text is plain. "Heavy rain has soaked the slopes above the east fork. Mud and rock could come down on the trail. Take the Cedar Loop instead."

---

## Data Model

```sql
mountains (
  id, name, slug, lat, lon, elevation_m, region,
  current_risk_level, last_analyzed_at, is_live bool,
  kind text  -- "mountain" or "hill"
)

trails (
  id, mountain_id, name,
  geom jsonb,          -- GeoJSON LineString
  length_km, elevation_gain_m
)

trail_segments (
  id, trail_id, seq,
  geom jsonb,
  start_mile, end_mile,
  risk_level, probability
)

analysis_runs (
  id, mountain_id, status,
  started_at, finished_at,
  agent_outputs jsonb  -- also holds the final Run view
)

hazards (
  id, mountain_id, run_id,   -- run_id null for a preview hazard
  type, severity, probability, confidence,
  geom jsonb,          -- GeoJSON Polygon
  drivers jsonb,
  what text, why text, how_to_avoid text,
  needs_review bool,
  trail_id, start_mile, end_mile,   -- the flagged miles
  bypass jsonb,                     -- null when no detour exists
  created_at
)

alerts (
  id, hazard_id, run_id,
  severity, title, body, recommended_action,
  discord_message_url, created_at
)                      -- unused since Discord was dropped
```

Seed Rainier plus two marker mountains (Huascarán, Mount Fuji). Every catalog row is `kind = "mountain"`. Seed one hill, Turtle Mountain, from `data/seed/hills.json`, `kind = "hill"`. Seed trails for Rainier only. Historical events are read from `data/seed/landslides.geojson`, not a table. The Frank Slide is not hand-placed.

---

## API Surface

```
GET  /health
GET  /mountains
GET  /mountains/{slug}                  → mountain, trails, active_hazard, historical_events, active_run_id
GET  /mountains/{slug}/layers/{layer}   → tile URL template (susceptibility, probability)
GET  /hills/{slug}                      → same detail shape, only when kind is hill
GET  /hills/{slug}/layers/{layer}       → the hill's tiles
GET  /hills/{slug}/risk-summary         → the hill page's scores
POST /mountains/{slug}/analyze          → { run_id }
GET  /runs/{run_id}
WS   /runs/{run_id}/stream              → RunUpdate and AgentEvent messages
GET  /forecast?mountain_id&trail_id
GET  /tiles/{layer}/{z}/{x}/{y}.png

Planned for 6.8 (steps 26 to 28):
GET  /mountains/{slug}/pressure-points  → PressurePoint[]
POST /mountains/{slug}/simulate         → { simulation_id }   no body: always the route most likely to fail
GET  /simulations/{simulation_id}
WS   /simulations/{simulation_id}/stream → the frames and steps, then each callout, then done
```

Simulations live in the API process, keyed by `simulation_id`, like runs. They write nothing to Postgres.

`/analyze` is allowed only when `is_live` is true (409 otherwise). A second call while a run is going returns the running run's id. Other mountains return their static seed risk.

---

## Build Plan

36 hours, four people: frontend, ML and data, backend and agents, product and pitch. Prep before the event is data and keys only, unless the rules allow a repo skeleton. The step-by-step status is in [implementation-steps.md](implementation-steps.md).

### Before the event

- Clip Rainier DEM, land cover, trails, and landslide points. Build the feature table.
- Keys: Gemini and xAI (either alone works). Open-Meteo and the terrain tiles need none. Mapbox is optional, for satellite imagery.
- Pick the two static marker mountains and their display risk.

### Hours 0–8: Something on screen (done)

- Globe with three markers and a fly-to.
- 3D terrain for Rainier, trail lines, shaded relief (satellite with a Mapbox token).
- FastAPI and Postgres seeded.
- Susceptibility raster tiled and visible as a toggle.

### Hours 8–18: The loop (done, except Model B)

- Model B with Open-Meteo. Probability tiles. One hazard polygon.
- Trail segments colored by risk. One bypass, even if the geometry is hand-authored.
- `/analyze`, seven agents (five analysts in parallel, then the Synthesizer and the Writer), WebSocket stream, agent panel.
- Hazard panel with the four fields.

### Hours 18–28: The two audiences (done)

- Hiker card using Alert Writer text, bypass drawn on the map.
- Empty, loading, and error states. If a run fails, the UI says so.

### Hours 28–36: Pitch

- Tighten motion and copy.
- 60–90 second backup video.
- Devpost draft with the real AUC and the real data sources.
- Finish wiring the mountain page: traces, Reactive Measures, trail scores, the overall score, and preventative measures come from the API. Check the five trails against the advisory after a fake-LLM run.
- Rehearse the live demo three times with real keys. Keep a finished run on screen in case the live call fails.

If you are behind, drop in this order:

1. The simulation's callouts, then the simulation itself (keep the panel's pressure points, or let the click fly straight in as it does today).
2. The two extra globe markers (Rainier alone still demos).
3. The susceptibility toggle (keep the 72-hour heat map).
4. A computed bypass (show a named bypass in text).
5. The Synthesizer as its own call (let Alert Writer merge the three reports).

Do not drop the globe, the heat map, or the agent stream.

---

## Demo Script

About two and a half minutes.

1. **(0:00)** Globe, rotating. "Hikers check the weather. Almost nobody checks the ground."
2. **(0:10)** Click Mount Rainier. The panel opens. "These are the five slopes most likely to fail in the next 72 hours."
3. **(0:25)** **Simulate.** The flow runs down to the trail, and the callouts appear. "If the worst one goes, here's where it reaches the trail, what rangers do, and what nearby hikers would be told."
4. **(0:50)** **Open ranger view.** Fly in. The mountain stands out gray on white, with its five at-risk trails lettered A to E.
5. **(1:00)** **View** on trail A. The camera flies to it, and the tooltip shows its score, slope, and primary factor.
6. **(1:15)** **Analyze now.** The Orchestrator dispatches the agents. "Agents check the slope, the rain, the trails, and the record, then one of them decides."
7. **(1:40)** Open a card's trace. "A router sends each agent to Gemini Flash or Grok, and the ranger can see how it reasoned."
8. **(2:00)** Reactive Measures. "Closures, sweeps, rescue staging, spotters, who to call, and the public notice, drafted and not sent."
9. **(2:20)** Back to the globe. "TerraSense. Know the ground before you go."

### Nepal and Tibet beat (optional, about 60 seconds)

Use this only after the Rainier loop has landed. Search **Everest**. Do not hunt for the pin among the 50 on the globe.

1. Hover the marker. The card shows the satellite preview, the region, and the risk badge.
2. Open the page. Everest is a built pack: real 30 m terrain, its own heat tiles, and the Everest Base Camp Trek cut into miles. "This heat is a **knowledge-driven index** for this box: slope, drainage, land cover, wetness, and curvature, weighted by what drives slope failure. It is not the Cascades model, it is not trained on Himalayan landslides, and it has no AUC. There is no Nepal forecast behind it."
3. One river line, then stop. "Monsoon rain loads these slopes. When they fail, debris reaches the valleys and the rivers below. We score the slope, not the river stage."
4. Annapurna I, Manaslu, and Kangchenjunga are catalog markers for the same news cycle: satellite hover and a synthetic drape, no pack and no scored trail.
5. Search **Kailash** and open it. This is the second built pack and the sharper current-event beat: the August 2026 floods and landslides on the **Nepal-Tibet border** cut the approach routes pilgrims use to reach it. Say where it actually is: "Kailash sits in Tibet, in China. Pilgrims reach it *through* Nepal, and that approach is what the weather closed."
6. The scored line is the **Kailash Kora**, the pilgrim circuit around the peak, which OpenStreetMap names 冈仁波齐转山. It is 46 km of the 52 km circuit, cut into 288 tenth-mile segments. Same honesty as Everest: the heat is the knowledge-driven index for this box, not a trained model and not a Tibet forecast.

**Analyze now** works here, because the pack is live. If you run it, say what the summit number is: the Cascades model reading a stand-in terrain sample, labeled `placeholder_terrain_sample` in the response, not measured ground at Everest. The safer demo is to leave the run on Rainier, which already showed the agents end to end.

---

## Devpost Write-Up Draft

Replace the brackets before submitting.

### Inspiration

Hikers check the forecast. They cannot easily check whether the slope above the trail has taken days of rain and is about to fail. The satellite and weather data to estimate that already exists. It is not written as "close this segment, take this bypass."

### What it does

TerraSense scores Mount Rainier for landslide risk over the next 72 hours. A click on the 3D globe opens a panel with the slopes most likely to fail, and a simulation plays a debris flow from the worst one down to the trail, with AI callouts for rangers and a draft notice for people nearby. The globe then opens onto a terrain map with a risk heat map, past landslide pins, and trails colored by segment. Five agents turn the scores into a ranger alert and a hiker forecast, and a side panel shows how each one reasoned. The forecast names a bypass.

### How we built it

**Data and ML.** Copernicus 30 m DEM features (slope, concave hollows, drainage proximity, wetness) and ESA WorldCover 2021 land cover are joined to 34 usable labels: one precise NASA event plus 33 official Washington Geological Survey inventory-derived points. A LightGBM susceptibility model trains on 7,351 mapped landslide pixels across the western Cascades (spatial-block ROC-AUC 0.82, 95% CI 0.78–0.85; 0.60 on Rainier's own 93 mapped slides). Model B multiplies its calibrated odds by rain odds fitted on 767 dated Pacific Northwest landslides (ROC-AUC 0.75, whole years held out) to make a relative 72-hour risk index.

**Agents.** Seven agents with Pydantic outputs: five analysts (Terrain, Weather, Trail, History, Route Scout) in parallel, then the Risk Synthesizer and the Alert Writer, streamed over a WebSocket. A router in code sends each call to Gemini Flash or Grok by task, stakes, and provider health, and falls back to the other on failure. Code checks every answer, sets confidence, and flags needs review when severities differ by two levels. A side panel shows each agent's model, the router's reasons, the facts it read, and its reasoning. The bypass is routed on the OpenStreetMap trail network.

**Frontend.** Next.js, React Three Fiber for the globe, MapLibre GL for 3D terrain.

### Challenges

[Fill in from the weekend. Likely: tile alignment, a blocked landslide catalog, agent latency.]

### What we learned

[Fill in. Likely: the useful output is the trail instruction, not the raster.]

### What's next

More mountains, a real ranger feedback loop, and slower signals such as InSAR. Not this weekend.

The same rain-on-steep-ground mechanism shows up in monsoon seasons in Nepal, so we built Mount Everest as a pack: real 30 m terrain, its own heat tiles, and the Everest Base Camp Trek cut into miles. That heat is a knowledge-driven terrain index for the Everest box, not a Himalaya-trained model and not a river-stage forecast; only Rainier has a landslide inventory dense enough to train and score on. Annapurna I, Manaslu, and Kangchenjunga stay catalog markers for the same news cycle. Failures upstream still matter because debris reaches valley corridors. A second trained region, and any river layer, stay after the hackathon.

---

## Risks

| Risk | What to do |
|---|---|
| Raster work blows the schedule | Precompute Model A. Only Model B runs live |
| The demo mountain looks uniformly safe or uniformly red | Done Sep 26: Model B's terrain weight was retuned so a storm reddens the susceptible valleys, not the whole box (see 6.3). The hazard is picked on the hero trail, not the whole box, so a storm that misses the Skyline loop shows no hazard zone |
| The landslide catalog stays unreachable | Download the CSV on another network and pass `--glc-csv`. Until then, say "knowledge-driven index" and show no AUC |
| Agents exceed a minute | Parallelize Terrain and Weather. Short JSON schemas. The router moves late calls to Gemini |
| No live LLM run before the demo | Rehearse with real keys. Keep a finished run on screen |
| Heat map does not sit on the terrain | XYZ tiles in EPSG:3857. Check in the first map session |
| Globe stutters | Three markers, modest textures |
| "Is this real science?" | Cite Guzzetti rainfall thresholds and NASA LHASA. Say this is a prototype of the last mile, trail to alert, not a replacement for an operational USGS product |
| Placeholder casualty stats | Source them or cut them from the slides |

---

## Out of Scope

Do not build these during HackGT. They are real follow-ons, and they will sink the demo if you start them.

- Rain what-if inputs ("what if it rains 6 inches"), or any other input to the simulation. The runout simulation in 6.8 replays today's worst slope and takes no inputs.
- Avalanche UI, agent, trail-action, and map-layer integration remains out of the HackGT demo scope. The parallel avalanche API returns a separate 24-hour model state and must be validated with avalanche labels before it is presented as an operational warning.
- Sending anything: SMS, email, Slack, Discord, push. Public notices in the simulation are drafts. Ranger signup, districts, acknowledge / escalate / dismiss.
- Auth.
- GPX download, public share pages, Open Graph images, browser geolocation.
- InSAR and Sentinel-1, SMAP as a required input, earthquake triggers, a CNN on DEM patches, SHAP plots.
- Live agent analysis for more than Mount Rainier. The hill page does not run the seven agents.
- A mountain model. One is planned for high peaks. It is not started. Hills use the existing landslide model.
- A scheduled ingest job. **Analyze now** is the product for the demo.
- Redis, PostGIS, S3 or R2, and a multi-service deploy you do not already know how to run.
- Writing trail closures back to a park system.

If the core loop is done and rehearsed, the only acceptable extra is a second live mountain using the same pipeline. Do not start that until a live run with real keys has finished twice.

---

## Decision Log

Changes to this spec after the build started. Each one is also reflected in the section it touches.

| Date | Decision |
|---|---|
| Sep 25, 2026 | MapLibre GL with AWS Terrain Tiles replaces Mapbox GL. No token needed. A Mapbox token switches the relief to satellite |
| Sep 25, 2026 | Discord dropped. The ranger alert stays in the app (step 24) |
| Sep 25, 2026 | Two LLM providers, Gemini Flash and Grok, with a router in code and a reasoning panel |
| Sep 25, 2026 | Model B pulled for a rebuild. The heat map is the labeled susceptibility stand-in until it lands |
| Sep 26, 2026 | Terrain retrained regionally (spatial CV AUC 0.82, Rainier-only 0.60) and Model B's rain weights fitted on 767 dated landslides (AUC 0.75). The point value and the heat map are a relative 72-hour index with its held-out skill shown in the card. The mountain page's trail scores come from the saved map |
| Sep 26, 2026 | Model B's terrain weight retuned (`w1` 2.4 to 7.0, center 0.5 to 0.75) so terrain gates the rain trigger. The landslide-risk endpoint returns a 0–1 `probability` on every in-domain click: the calibrated one when it exists, else the labeled Model B estimate (6.3) |
| Sep 25, 2026 | Susceptibility is a knowledge-driven index until landslide labels exist |
| Sep 25, 2026 | A globe click opens a mountain panel with pressure points and a runout simulation with AI callouts (6.8). The old "no simulation mode" rule now means no rain what-if inputs. Avalanches stay out |
| Sep 25, 2026 | The backend fans out five analysts (Terrain, Weather, Trail, History, Route Scout), then the Risk Synthesizer decides routes and the ranger response, then the Alert Writer. Runs end in an advisory (6.4) |
| Sep 25, 2026 | The globe goes light and evenly lit, with mountain-logo markers. The mountain map renders the mountain gray on white surroundings, framed from its elevation |
| Sep 25, 2026 | The ranger page, first called the hill detail card, is the mountain page (6.2): a 55/45 split, top five trails with map markers and **View**, preventative measures, an orchestrator with five agent cards and inline traces, and Reactive Measures. The rain section, the reasoning side panel, and the hiker card leave the page. Trail scores and the run are illustrative until the models land |
| Sep 26, 2026 | The existing regional LightGBM and Model B score hills. The first hill is Turtle Mountain, Crowsnest Pass, Alberta. Rainier stays the demo mountain on the same code until a mountain model exists. That model is not started. Avalanche and snowpack stay out of scope. The Frank Slide was a rockslide, so the rain trigger is not an explanation of 1903 |
| Sep 26, 2026 | Nepal / Tibet current-event set. Mount Everest and Mount Kailash are both built as packs and go live from their own rasters: real tiles, the Everest Base Camp Trek and the Kailash Kora in miles. Kailash is in Tibet, China, reached through Nepal; the copy says so rather than calling it a Nepali peak. Its heat is a knowledge-driven index, never called trained and never called a Nepal forecast. Annapurna I, Manaslu, and Kangchenjunga stay catalog markers. Rivers are one spoken line about debris in valleys, not a layer or a forecast. See `context/docs/nepal-mountains-build.md` |

---

## Glossary

- **DEM.** Digital elevation model. Each pixel is an elevation.
- **Susceptibility.** How prone a slope is to sliding, ignoring today's weather.
- **Triggering.** Rain that turns a susceptible slope into a near-term hazard.
- **Debris flow.** A fast mix of mud, rock, and water that follows a drainage. This is the hiker-relevant failure mode.
- **TWI.** Topographic wetness index. Where water tends to accumulate.
- **LHASA.** NASA's global landslide hazard assessment model. Prior art for the nowcast, not for the trail instruction.
- **Stand-in.** The susceptibility map served as the 72-hour layer until Model B lands. Labeled everywhere it shows.
- **Hero trail.** The Skyline loop from Paradise, the trail the assessment scores by mile.
- **Pressure point.** One of the up to five slopes most likely to fail on the 72-hour map: a connected cluster at Moderate or above, ranked by peak and size.
- **Runout.** How far and where a failed slope's material travels before it stops. The simulation traces it on the DEM.
- **Skip-route.** The bypass that avoids the flagged trail segment.
- **Router.** The code that picks Gemini Flash or Grok for each agent call and records why.
- **Run.** One pass of the probability map plus the seven agents for Mount Rainier.
- **Mountain page.** The ranger page at `/mountains/[slug]`. It was first called the hill detail card.
- **Hill.** A place kind scored by the existing landslide model. The first one is Turtle Mountain, Crowsnest Pass, Alberta. The name on the map can still say Mountain.
