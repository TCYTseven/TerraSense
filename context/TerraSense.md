# TerraSense

> Landslide hazard intelligence for hikers and park rangers, built on satellite terrain data.

HackGT scope. This document is the build target. If a feature is not in [Hackathon scope](#hackathon-scope), do not build it.

---

## Table of Contents

1. [One-Liner](#one-liner)
2. [Hackathon Scope](#hackathon-scope)
3. [The Problem](#the-problem)
4. [What TerraSense Does](#what-terrasense-does)
5. [Who It Is For](#who-it-is-for)
6. [Core Features](#core-features)
7. [User Flows](#user-flows)
8. [System Architecture](#system-architecture)
9. [Data Sources](#data-sources)
10. [ML Pipeline](#ml-pipeline)
11. [Agent Design](#agent-design)
12. [Tech Stack](#tech-stack)
13. [Design Language](#design-language)
14. [Data Model](#data-model)
15. [API Surface](#api-surface)
16. [Build Plan](#build-plan)
17. [Demo Script](#demo-script)
18. [Devpost Write-Up Draft](#devpost-write-up-draft)
19. [Risks](#risks)
20. [Out of Scope](#out-of-scope)
21. [Glossary](#glossary)

---

## One-Liner

TerraSense reads terrain and weather for a mountain, predicts where a landslide is likely in the next 72 hours, and turns that into two outputs: an alert a park ranger can act on, and a plain-language forecast that tells a hiker which trail segment to skip.

---

## Hackathon Scope

Build one convincing loop, not a platform.

**In**

- A 3D globe. Click Mount Rainier and fly in.
- Two extra mountains as static globe markers so the globe is not a single dot. They do not run live analysis.
- One live mountain: **Mount Rainier**. Precompute its terrain features before the event.
- Landslide risk only. A static susceptibility layer and a 72-hour probability layer driven by recent rain.
- Historical landslide pins from a public catalog.
- Trails colored by risk, plus one alternate route that avoids the worst segment.
- Five agents that stream their work into the UI.
- One live Discord alert with a link back to the hazard.
- A hiker forecast card in plain language.

**Out**

See [Out of Scope](#out-of-scope). The short version: no simulation mode, no extra hazard types, no SMS or email, no accounts, no GPX export, no InSAR.

**Demo proof**

A judge can spin the globe with smooth, clean animations, click on mountains to fly in with a seamless transition, open Rainier, see the heat map appear, watch the agents run, see a Discord message arrive, and read a hiker card that names a bypass.

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
3. **Decide.** Five agents read the scores, the weather, and the trail geometry, then agree on a severity and a sentence a person can act on.
4. **Deliver.** Show it on a 3D globe and a terrain map. Push one alert to Discord. Show the hiker a forecast card and a bypass.

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

- React Three Fiber and a globe helper (`three-globe` or `react-globe.gl`).
- Dark satellite-textured Earth with a light atmospheric glow.
- Three markers. Color encodes overall risk: green, amber, or red. Rainier is live. The other two use a fixed risk value loaded from seed data.
- Drag, zoom, and a slow idle rotation.
- Hover shows mountain name, risk level, and last refresh time.
- Click flies the camera in and opens the mountain view.
- A search box accepts "Mount Rainier" and flies there.

The globe is the demo hook. Keep it small and fast. Three markers is enough.

### 6.2 Mountain View

Clicking Rainier opens a Mapbox GL map with 3D terrain (exaggeration about 1.5) and a satellite basemap.

**Layers**

- **72-hour landslide probability.** The live heat map. This layer is on by default.
- **Susceptibility.** The static "this slope can fail" layer. One toggle.
- **Trails.** Lines from a pre-downloaded OpenStreetMap extract, colored by segment risk.
- **Historical events.** Pins from the landslide inventory.
- **Hazard pin.** One primary pin on the worst cluster. Clicking it opens the detail panel.

**Hazard detail**

Four fields, always in this order:

1. What it is.
2. Why the model flagged it.
3. Confidence.
4. How to avoid it.

**Side panel**

- Mountain name, elevation, region.
- Overall risk and one plain-language sentence.
- Trails with a risk score.
- Button: **Analyze now**.
- Button: **Hiker forecast**.

Weather stays in the panel as text (last 72 hours of rain, next 24 hours). It is not a map layer.

### 6.3 Landslide Model

Two stages. Both stay explainable.

**Model A, susceptibility (offline)**

- One row per pixel: slope, aspect, curvature, elevation, distance to drainage, land cover, topographic wetness index.
- Label: landslide inventory point, buffered, versus sampled stable terrain.
- Model: LightGBM binary classifier.
- Split by space, not by random row, so neighboring pixels do not leak into the test set.
- Output: susceptibility from 0 to 1, saved as a raster before the demo.
- Record AUC and precision at the High threshold. Publish the number you get. Do not treat 0.85 as a gate.

**Model B, triggering (live)**

- Inputs: Model A score, 3-day and 7-day precipitation from Open-Meteo, and forecast rain over the next 72 hours.
- Method: a rainfall intensity-duration threshold (Guzzetti-style) plus an antecedent moisture index from recent rain, blended with susceptibility:

`P = sigmoid(w1 · susceptibility + w2 · rainfall_exceedance + w3 · moisture_index)`

- Tune weights on the dated events you actually have. If that set is tiny, say so and keep the weights explicit.
- Categories: Low < 0.2, Moderate 0.2–0.45, High 0.45–0.7, Extreme > 0.7. Adjust so Rainier shows a visible High zone for the demo, and document the adjustment.

Feature importance from LightGBM is enough for the "why" sentence. Skip SHAP.

### 6.4 Agents

Five LLM calls with separate prompts. A Discord send is ordinary code, not an agent.

| Agent | Job | Output |
|---|---|---|
| Terrain Analyst | Finds the worst cluster on the probability raster and describes where it is | One hazard zone: type, severity, drivers, confidence |
| Weather Analyst | Says whether the next 24–72 hours make that zone worse, stable, or better | A modifier and a short weather note |
| Trail Analyst | Intersects the zone with trails and picks one bypass | Affected mile range, bypass name, added distance, added elevation |
| Risk Synthesizer | Combines the three reports into one severity and one confidence | Final level, confidence, `needs_review` if the reports disagree |
| Alert Writer | Writes the ranger alert and the hiker card | Two short texts |

Run Terrain and Weather in parallel, then Trail, then Synthesizer, then Alert Writer. Stream each result to the UI.

Consensus rule: if severity ratings differ by two or more levels, set `needs_review` and phrase the alert as an advisory.

### 6.5 Ranger Alert

After Alert Writer finishes, the server posts to a Discord webhook.

The message includes hazard type, severity, trail and mile marker, confidence, the recommended action (monitor or close), a one-paragraph reason, and a link that opens the map on that hazard.

Hardcode the webhook URL. There is no ranger account, no inbox, and no acknowledge button.

### 6.6 Hiker Forecast

A card, not a second product.

- Trail name, today's level (Low / Moderate / High / Extreme), and one sentence.
- The bypass: name, added distance, added elevation.
- The same bypass drawn on the mountain map.

The Alert Writer produces the sentence. No account, no share image, no file download.

---

## User Flows

### Ranger alert

1. The demo starts from **Analyze now** (a scheduled overnight job is out of scope).
2. Model B runs on the cached Rainier stack plus fresh Open-Meteo rain.
3. Terrain and Weather run together. Trail Analyst names the affected segment and a bypass. The Synthesizer sets High or flags `needs_review`. Alert Writer drafts both texts.
4. The server posts to Discord.
5. The judge opens the link and sees the pin, the heat map, and the four-field panel.

### Hiker check

1. Open the globe, click Mount Rainier.
2. Open **Hiker forecast** for the flagged trail.
3. Read the level, the sentence, and the bypass (added distance and elevation) on the map.

### Judge demo

1. Land on the rotating globe.
2. Search or click Mount Rainier. Fly in.
3. Show the probability heat map, then toggle susceptibility and historical pins.
4. Open the hazard pin and read the four fields.
5. Click **Analyze now**. The agent rows fill in.
6. Show the Discord message on a second screen.
7. Open the hiker card and the bypass.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     FRONTEND (Next.js)                      │
│   3D Globe (R3F)  →  Mountain map (Mapbox)  →  Hiker card   │
│              WebSocket (agent stream)    REST               │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                    API (FastAPI)                            │
│   /mountains   /analyze   /forecast   /alerts               │
│   in-process run state, WebSocket relay                     │
└────────────┬───────────────────────┬───────────────────────┘
             │                       │
   ┌─────────▼──────────┐   ┌────────▼─────────┐
   │  ML (Python)       │   │  5 agents        │
   │  Model B on cached │   │  LLM calls       │
   │  Rainier stack     │   │                  │
   └─────────┬──────────┘   └────────┬─────────┘
             │                       │
   ┌─────────▼───────────────────────▼─────────┐
   │  Postgres: mountains, trails, hazards,     │
   │  runs, alerts. GeoJSON stored as JSON.     │
   │  Precomputed rasters/tiles on disk.        │
   └────────────────────────────────────────────┘
             ▲
   ┌─────────┴──────────────────────────────────┐
   │  Before the event: DEM, land cover, trails,│
   │  landslide points. Live: Open-Meteo only.  │
   └────────────────────────────────────────────┘
```

Keep the API thin. Model B and the agents can run in the same Python service for the demo. Move inference to Modal only if a local run is too slow or the laptop fans become the demo.

Serve map tiles from the app. One mountain does not need object storage.

Store agent state in the API process, keyed by `run_id`. One demo mountain does not need Redis.

---

## Data Sources

Download and clip these before the event. Everything is for Mount Rainier unless noted.

| Data | Source | Use |
|---|---|---|
| Elevation | Copernicus DEM 30 m, or USGS 3DEP if the clip is easier | Slope, aspect, curvature, wetness index |
| Land cover | NLCD or ESA WorldCover, one of them | Model A feature |
| Landslide points | NASA Global Landslide Catalog and/or a USGS/state inventory for the Rainier area | Model A labels and map pins |
| Precipitation | Open-Meteo | Model B, live |
| Trails | OpenStreetMap, saved ahead of time | Trail risk and the bypass |
| Basemap | Mapbox satellite | Mountain view |

The other two globe markers need a name, a coordinate, and a static risk level. They do not need rasters.

---

## ML Pipeline

### Before the event

1. Clip a DEM to a Rainier bounding box.
2. Build slope, aspect, curvature, topographic wetness index, and distance to drainage with rasterio (and richdem if wetness is awkward in pure rasterio).
3. Resample land cover to the same 30 m grid.
4. Buffer inventory points to about 50 m for positives. Sample negatives from the rest of the box at roughly 1:3.
5. Save a feature table and the susceptibility raster.
6. Save trail lines as GeoJSON, split into segments with mile markers you can explain on stage.

### At the event

1. Train LightGBM if you did not finish training beforehand. Spatial split: hold out one part of the box, or a nearby area, as the test set.
2. Write the Model B function so it only needs the cached susceptibility raster and an Open-Meteo response.
3. Turn the probability raster into XYZ tiles in Web Mercator (EPSG:3857) so Mapbox lines up with the terrain. Check alignment early.
4. Extract the worst cluster as one polygon for the hazard pin.

Target: Model B plus tiling finishes in under 30 seconds. If tiling is slow, pre-tile susceptibility and only recolor the probability overlay from a coarse grid.

---

## Agent Design

Each agent is a function that receives the `run_id`, calls one model with a fixed prompt, and returns JSON validated with Pydantic. The API stores that JSON on the run and pushes it down the WebSocket.

**Models**

- Terrain, Weather, and Trail: a fast model.
- Synthesizer and Alert Writer: a stronger model. These two judge and write.

**Tools**

- `get_raster_summary(mountain_id)` returns cluster stats you precomputed in Python. The agent does not scan pixels.
- `get_trail_segments(mountain_id)`
- `get_weather(lat, lon)`
- `get_historical_events(lat, lon, radius_km)` so the Terrain or Synthesizer note can mention a past debris flow without a sixth agent.

Compute the bypass in Python (a short path on the trail graph, or a hand-authored Cedar Loop if the graph is not ready). The Trail Analyst explains that result. It does not invent geometry.

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

Weights are constants in code. If two severity labels differ by two levels, set `needs_review`.

Target: the five calls finish in about a minute. Cap each output at a short JSON object plus a few sentences.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router) + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Globe | React Three Fiber + Three.js |
| Map | Mapbox GL JS with 3D terrain |
| Realtime | FastAPI WebSocket |
| API and agents | FastAPI, Pydantic |
| ML | LightGBM, rasterio, GeoPandas or Shapely |
| Database | Postgres (Neon or Supabase). Geometries as GeoJSON |
| LLMs | One provider is enough. A second provider is optional |
| Alert | Discord webhook |
| Deploy | Vercel for the frontend. API on Railway, Modal, or a laptop tunnel |

Skip auth, Redis, PostGIS, object storage, Docker-as-a-requirement, Twilio, and email for this build.

---

## Design Language

Dark and operational, like a small dispatch screen. The hiker card is the only softer surface.

**Color**

- Background `#0D0C0A` to `#13120F`.
- Panels `#1A1814`, 1 px border at about 10% of the text color.
- Interactive accent `#7FDDE6`.
- Risk only: green `#22C55E`, amber `#F59E0B`, orange `#F97316`, red `#EF4444`.
- Text `#ECE6DC`, muted `#9C9387`.

**Type**

- UI: Inter, Geist, or Space Grotesk.
- Coordinates, times, and scores: JetBrains Mono or Geist Mono.

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
  current_risk_level, last_analyzed_at, is_live bool
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
  agent_outputs jsonb
)

hazards (
  id, mountain_id, run_id,
  type, severity, probability, confidence,
  geom jsonb,          -- GeoJSON Polygon
  drivers jsonb,
  what text, why text, how_to_avoid text,
  needs_review bool,
  created_at
)

alerts (
  id, hazard_id, run_id,
  severity, title, body, recommended_action,
  discord_message_url, created_at
)
```

Seed Rainier plus two marker mountains. Seed trails for Rainier only.

---

## API Surface

```
GET  /mountains
GET  /mountains/{id}
GET  /mountains/{id}/layers/{layer}     → tile URL template
POST /mountains/{id}/analyze            → { run_id }
GET  /runs/{run_id}
WS   /runs/{run_id}/stream
GET  /forecast?mountain_id&trail_id
```

`/analyze` is allowed only when `is_live` is true. Other mountains return their static seed risk.

---

## Build Plan

36 hours, four people: frontend, ML and data, backend and agents, product and pitch. Prep before the event is data and keys only, unless the rules allow a repo skeleton.

### Before the event

- Clip Rainier DEM, land cover, trails, and landslide points. Build the feature table.
- Keys: Mapbox, an LLM provider, Discord webhook, Open-Meteo (no key).
- Pick the two static marker mountains and their display risk.

### Hours 0–8: Something on screen

- Globe with three markers and a fly-to.
- Mapbox terrain for Rainier, trail lines, satellite basemap.
- FastAPI and Postgres seeded.
- Susceptibility raster tiled and visible as a toggle.

### Hours 8–18: The loop

- Model B with Open-Meteo. Probability tiles. One hazard polygon.
- Trail segments colored by risk. One bypass, even if the geometry is hand-authored.
- `/analyze`, five agents, WebSocket stream, agent panel.
- Hazard panel with the four fields.

### Hours 18–28: The two audiences

- Discord post at the end of a run, with a deep link.
- Hiker card using Alert Writer text, bypass drawn on the map.
- Empty, loading, and error states. If a run fails, the UI says so.

### Hours 28–36: Pitch

- Tighten motion and copy.
- 60–90 second backup video.
- Devpost draft with the real AUC and the real data sources.
- Rehearse the live demo three times. Keep a finished run on screen in case the live call fails.

If you are behind, drop in this order:

1. The two extra globe markers (Rainier alone still demos).
2. The susceptibility toggle (keep the 72-hour heat map).
3. A computed bypass (show a named bypass in text).
4. The Synthesizer as its own call (let Alert Writer merge the three reports).

Do not drop the globe, the heat map, the agent stream, or the Discord message.

---

## Demo Script

About two minutes.

1. **(0:00)** Globe, rotating. "Hikers check the weather. Almost nobody checks the ground."
2. **(0:15)** Open Mount Rainier. Turn on the heat map. "This is 72-hour landslide probability from terrain and recent rain."
3. **(0:35)** Open the hazard pin. Read what, why, confidence, and what to do.
4. **(0:55)** **Analyze now.** Agents stream. "Five agents check the slope, the forecast, and the trail, then agree."
5. **(1:20)** Discord message on the second screen. "A ranger gets the segment, the severity, and a link."
6. **(1:40)** Hiker card and the bypass on the map. "A hiker gets one sentence and a way around it."
7. **(1:55)** Back to the globe. "TerraSense. Know the ground before you go."

---

## Devpost Write-Up Draft

Replace the brackets before submitting.

### Inspiration

Hikers check the forecast. They cannot easily check whether the slope above the trail has taken days of rain and is about to fail. The satellite and weather data to estimate that already exists. It is not written as "close this segment, take this bypass."

### What it does

TerraSense scores Mount Rainier for landslide risk over the next 72 hours. A 3D globe opens onto a terrain map with a risk heat map, past landslide pins, and trails colored by segment. Five agents turn the scores into a ranger alert and a hiker forecast. The alert posts to Discord. The forecast names a bypass.

### How we built it

**Data and ML.** [DEM features, land cover, landslide labels, LightGBM with a spatial split, rainfall-threshold trigger using Open-Meteo. Report AUC and the threshold you used.]

**Agents.** [Five agents, parallel first step, Pydantic outputs, WebSocket stream, disagreement flagged as needs review.]

**Frontend.** Next.js, React Three Fiber for the globe, Mapbox GL for 3D terrain.

**Alerting.** Discord webhook with a deep link. No accounts.

### Challenges

[Fill in from the weekend. Likely: tile alignment, a small labeled set, agent latency.]

### What we learned

[Fill in. Likely: the useful output is the trail instruction, not the raster.]

### What's next

More mountains, a real ranger feedback loop, and slower signals such as InSAR. Not this weekend.

---

## Risks

| Risk | What to do |
|---|---|
| Raster work blows the schedule | Precompute Model A. Only Model B runs live |
| The demo mountain looks uniformly safe or uniformly red | Tune category thresholds and document it. Pick a trail that crosses a real steep drainage |
| Agents exceed a minute | Parallelize Terrain and Weather. Short JSON schemas. Fast models for the first three |
| Heat map does not sit on the terrain | XYZ tiles in EPSG:3857. Check in the first map session |
| Globe stutters | Three markers, modest textures |
| Discord fails on stage | Keep a screenshot of a successful alert, and keep the in-app alert text visible |
| "Is this real science?" | Cite Guzzetti rainfall thresholds and NASA LHASA. Say this is a prototype of the last mile, trail to alert, not a replacement for an operational USGS product |
| Placeholder casualty stats | Source them or cut them from the slides |

---

## Out of Scope

Do not build these during HackGT. They are real follow-ons, and they will sink the demo if you start them.

- Simulation mode ("what if it rains 6 inches").
- Hazard types other than landslide / debris flow: rockfall, flash flood, avalanche, exposure, river crossings, lightning, heat, wildlife, closures.
- SMS, email, Slack, push, ranger signup, districts, acknowledge / escalate / dismiss.
- Auth.
- GPX download, public share pages, Open Graph images, browser geolocation.
- InSAR and Sentinel-1, SMAP as a required input, earthquake triggers, a CNN on DEM patches, SHAP plots.
- Live analysis for more than Mount Rainier.
- A scheduled ingest job. **Analyze now** is the product for the demo.
- Redis, PostGIS, S3 or R2, and a multi-service deploy you do not already know how to run.
- Writing trail closures back to a park system.

If the core loop is done and rehearsed, the only acceptable extra is a second live mountain using the same pipeline. Do not start that until the Discord alert has succeeded twice.

---

## Glossary

- **DEM.** Digital elevation model. Each pixel is an elevation.
- **Susceptibility.** How prone a slope is to sliding, ignoring today's weather.
- **Triggering.** Rain that turns a susceptible slope into a near-term hazard.
- **Debris flow.** A fast mix of mud, rock, and water that follows a drainage. This is the hiker-relevant failure mode.
- **TWI.** Topographic wetness index. Where water tends to accumulate.
- **LHASA.** NASA's global landslide hazard assessment model. Prior art for the nowcast, not for the trail instruction.
- **Skip-route.** The bypass that avoids the flagged trail segment.
- **Run.** One pass of Model B plus the five agents for Mount Rainier.
