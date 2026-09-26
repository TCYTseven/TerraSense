# Nepal mountain + river — lightweight demo tie-in

Planning doc only. **No new services, no river model, no second “live” ML region.** Fits [TerraSense.md](../TerraSense.md) hackathon scope: **Mount Rainier stays the only fully live peak**; Nepal is a **timely catalog story** on infrastructure we already have.

Status: superseded. Build Everest as a pack and feature the other Nepal peaks using [nepal-mountains-build.md](nepal-mountains-build.md). The demo script in [TerraSense.md](../TerraSense.md) still applies, with the index labeled as an index.

---

## Why this doc

Judges and Devpost readers respond to **current events**. Nepal’s **monsoon season** routinely brings **heavy rain, landslides on steep slopes, and swollen rivers** that cut trekking corridors and valley roads. TerraSense is landslide-first, not a flood-forecast product—but we can **name the same weather driver** (rain on terrain) and show **one Himalayan peak** on the globe without building hydrology.

This plan uses **seed data, copy, and demo flow** only. Rainier remains the proof of full pipeline depth.

---

## Product boundary (do not cross without a spec change)

| In scope for Nepal tie-in | Out of scope |
|---------------------------|--------------|
| One featured **catalog** peak (recommended: **Mount Everest** or **Manaslu**) | Second trained regional model for the Himalaya |
| Static **`current_risk_level`** bumped for demo (e.g. `high`) | River discharge, gauge APIs, flood polygons |
| Existing **synthetic susceptibility** drape + **satellite hover** image | Real-time news or incident ingestion |
| Optional **`Analyze now` location run** (summit-level agents, no Rainier trails) | Discord / external alerting |
| Demo script + Devpost paragraph citing **rain → slope failure → valley impacts** | Promising river height or evacuation zones |

**River** appears as **narrative context** (“debris and saturated slopes feed major rivers below”), not as a modeled layer.

---

## What we already have (no new infra)

| Asset | Location | Use for Nepal moment |
|-------|----------|----------------------|
| Everest in catalog | `data/seed/mountains.json`, `mountains_test.json` | Globe pin, search “Everest” |
| Satellite hover URL | `mountain_satellite_images` / `data/seed/satellite_images.json` | Hover card preview |
| 3D terrain + synthetic heat | `frontend/lib/synthetic-heatmap.ts`, layer API | Catalog peak mountain page |
| Everest pack (step 32) | `data/seed/packs/mount-everest/` | EBC trek lines, optional **Simulate** if pack raster is built and peak marked live |
| Location analyze | `POST /mountains/{slug}/analyze` for non-Rainier | Seven agents on **summit context**, no mile-scored Skyline |
| Open-Meteo in runs | `backend/app/weather.py` | Real rain numbers in agent copy when keys/network available |

**Default globe** still shows ~50 spaced pins; Nepal appears when the user **searches** or if we temporarily raise `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` / ensure a Himalaya pin is in the selected set (optional, one env var—no code required).

---

## Recommended hero: Mount Everest (`mount-everest`)

**Why Everest (vs inventing a new slug):** Already in seed, satellite image, pack folder, and team docs. Story: **Khumbu / EBC corridor**, monsoon rain on steep moraine and glacial terrain, ** Dudh Koshi and other rivers** carrying sediment when slopes fail upstream.

**Alternate:** `manaslu` (also in satellite seed)—stronger “remote peak” story, less pack work if EBC pack is incomplete.

---

## Minimal implementation checklist

Work in order. Each row is independently shippable.

### A. Data — skipped

Everest is already in the test seed at `high`, with region `Mahalangur Himal, Nepal / China`. The hover badge follows the model summit score, so a seed edit would not change the card.

### B. Pack — skipped

Rainier carries **Simulate**. No Everest raster build for the pitch.

### C. Copy — done

- [x] Nepal beat in [TerraSense.md](../TerraSense.md) Demo Script: search Everest, hover, open the page, label the heat as illustrative, one river sentence. No **Analyze now**.
- [x] Devpost **What's next** paragraph: same rain-on-slope mechanism, not a Himalaya forecast and not a river-stage model.

### D. Historical pin — skipped

History reads `data/seed/packs/<slug>/landslides.geojson`. A point in Rainier's `landslides.geojson` would not appear on an Everest run.

---

## Demo narrative (copy-paste starter)

> “Mount Rainier is where we trained and validated—spatial landslide susceptibility plus 72-hour rain. The same mechanism drives this week’s headlines in Nepal: intense monsoon rain on steep Himalayan terrain. Here’s Everest as a catalog peak: satellite context, terrain-shaped risk view, and agents reading live weather at the summit—not a separate flood model, but the **slope failure** side of the story that feeds rivers below.”

Adjust dates and news references the day of the demo; keep **honesty** about illustrative vs live scoring.

---

## River angle without a “river product”

Use **one concept**, repeated in talk track:

```text
Rain → slope saturation → landslide/debris flow → material enters river corridors
```

| Layer in app | River mention |
|--------------|----------------|
| Globe hover | None required |
| Mountain page | Optional subtitle under risk badge: “Heavy rain period · valley corridors sensitive to upstream debris” |
| Agent Weather card | Already shows precipitation; narrator links to valleys |
| Reactive Measures | Rainier only today; on Everest location run, use generic agent output |

**Do not** add a MapLibre river line or hydrology API for the hackathon unless scope changes.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Implies we predict Kathmandu flooding | Script: “slope hazard intelligence, not river stage forecasting” |
| Everest `Analyze` quality poor (stand-in terrain) | Say “location advisory”; show Rainier for scored trails |
| Pack not built | Synthetic heat + satellite only |
| Too many pins, Everest hard to find | Search-first demo; optional seed one-line bump to `is_live` false but featured in README |

---

## Effort summary

| Track | Task | Size |
|-------|------|------|
| Data | Risk level + region copy in seed | S |
| Backend | None required | — |
| Frontend | Optional one-line subtitle on mountain page | S |
| ML | Pack build for EBC | M (optional) |
| Product | Demo + Devpost paragraphs | S |

**Total minimum path:** seed tweak + demo script (**S**, no code).

---

## Decisions (locked)

1. **Hero:** `mount-everest`. Search for it. The test seed already has `current_risk_level: high` and region `Mahalangur Himal, Nepal / China`. The hover badge still follows the model summit score, not that seed color.
2. **Analyze on Nepal:** No, during the demo. The page already explains a location run. Rainier carries **Analyze now**.
3. **Pack / Simulate:** No. Rainier carries **Simulate**. Do not add a Nepal point to Rainier's `landslides.geojson`; History reads `data/seed/packs/<slug>/landslides.geojson`.

---

## After hackathon (explicitly not this doc)

- Regional labels and training windows for Himalaya.
- Incident feed or geo-fenced “current event” mode.
- Partnership copy with Nepal agencies.

---

## Related repo docs

- [seeding-and-catalog.md](seeding-and-catalog.md) — how pins load
- [9-26-todo.md](../9-26-todo.md) — open steps
- [data/AGENTS.md](../../data/AGENTS.md) — pack formats
- Step 32 in [implementation-steps.md](../implementation-steps.md) — Everest pack
