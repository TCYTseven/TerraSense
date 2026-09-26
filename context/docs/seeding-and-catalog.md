# Mountain and trail data: seeding vs API calls

Status as of Saturday, Sep 26, 2026. This is how the globe gets peaks and how Rainier gets trails—what is committed, what runs at deploy, and what never runs on page load.

## TL;DR

| Data | Globe / app source | External API on page load? |
|------|-------------------|----------------------------|
| **Mountain pins (catalog)** | `SEED_MODE=mountainstest` loads `data/seed/mountains_test.json` (138). `reseed` loads `data/seed/mountains.json` (1000). Both go Postgres → `GET /mountains` | **No** |
| **Trail lines & miles (Rainier)** | `data/seed/trails.geojson`, `trail_segments.geojson`, `trail_network.geojson` → Postgres | **No** |
| **Weather (analyze)** | Open-Meteo inside a run only | **No** on globe load |
| **LLM agents** | Gemini / xAI on **Analyze** only | **No** on globe load |

If the globe shows only **two or three** pins, Postgres still has the old three-peak seed. The committed catalogs are the 138-peak test file (default) and the 1000-peak dump. Load one with `app.seed`, then restart the API.

---

## Mountain catalog (globe pins)

### What the user sees

- Home page calls **`GET /mountains`** (via `frontend/lib/api.ts` → `getMountains()`).
- Each row is a **name, lat/lon, elevation, region, placeholder risk color**, and `is_live`.
- Only **`mount-rainier`** has `is_live: true` (full analyze, layers, Rainier trails). Other peaks are **clickable catalog markers** with 3D terrain at their coordinates—not full landslide pipeline.

### Runtime (fast, no rate limits)

| Step | When | Speed (typical) |
|------|------|-----------------|
| Browser → `GET /mountains` | Every globe load | **&lt; 50 ms** (Postgres read; ~1k rows is fine) |
| Empty DB → load JSON | First request if table empty | **&lt; 100 ms** (read `mountains.json`, upsert) |
| `POST /mountains/catalog/sync` | Manual / ops only | Same as above; **does not** call Wikidata or Overpass |

Implementation: `backend/app/mountain_catalog.py` (`ensure_catalog`, `sync_catalog`), wired from `backend/app/routes/mountains.py`.

**Important:** The API **does not** refresh peaks from the internet at runtime. Mountain positions do not change day to day; the committed JSON is the source of truth.

### Offline regeneration (~1k peaks target)

Run from **`backend/`** when you want to refresh the committed file (e.g. after fixing the Overpass query):

```bash
python -m app.mountain_catalog --write-seed --source overpass
python -m app.seed
```

| Source | Command flag | Speed / reliability (observed) |
|--------|--------------|--------------------------------|
| **Overpass (OSM peaks)** | `--source overpass` (**default**) | **~5–20 minutes**: **120 tiles** (10 latitude bands × 12 longitude slices of 30°) fetched by 4 parallel workers, each request starting on a different mirror (~1 in-flight query per public mirror), up to 3 attempts per tile rotating through the 4 mirrors, per-tile counts logged; a tile that times out splits in half along its longer axis and the halves retry (up to 5 splits). Whole-band (360° of longitude) queries **timed out on the dense northern bands**, which is how an earlier seed ended up all Antarctica/Patagonia with one NH peak. Use **`out body`** so nodes include lat/lon (`out tags` previously produced almost empty seeds). |
| **Wikidata** | `--source wikidata` or `auto` | Often **HTTP 429** (≈1 request/minute during outages). Fine for occasional manual runs, not for automation. |
| **Wrapper** | `python ml/scripts/fetch_mountains_wikidata.py` | Calls the same module as above. |

Filter (Overpass path): named `natural=peak` with an `ele` tag, **elevation ≥ 1800 m** (filtered server-side with `if:number(t["ele"])>=1800`; 1800 m keeps the Alps, US Rockies, and the Japanese Alps in without flooding the file with foothills; `[timeout:45]` so a too-dense tile fails fast and splits instead of burning 90 s per probe). Selection: after `dedupe_nearby` (2-decimal lat/lon), `space_out` keeps only the **highest peak per 1° neighborhood** (~110 km) so a ridge line never renders as one stack of pins; then **every occupied latitude band gets an even share** of the ~1000 slots (a band with fewer peaks donates its leftover to the fuller bands), and **each band's quota round-robins across its 30° longitude slices** highest-first — so the Rockies, the Alps, the Himalaya, and Japan all land pins instead of whichever single range is tallest. `--write-seed` **refuses to overwrite** the committed file when fewer than 500 rows come back (mass tile failure). Elevations above **8850 m** are rejected as mistagged OSM data. Always merge **`mount-rainier`** (live) plus the two featured statics **`mount-fuji`** and **`huascaran`** under their famous names — OSM tags those summits by their local point names, like Fuji's Kengamine — and drop picked peaks within 1° of any merged pin so nothing stacks. The fetch also caches the raw rows in `data/raw/overpass_peaks_raw.json` (gitignored) — re-tune selection without re-fetching via `--write-seed --source cache`.

After write + seed, commit **`data/seed/mountains.json`** so deploys and teammates never need Overpass.

### Current file status

As of Saturday, Sep 26, 2026:

| File | Rows | When it loads |
|---|---|---|
| `data/seed/mountains_test.json` | 138 | `SEED_MODE=mountainstest` (the default in `.env.example`) |
| `data/seed/mountains.json` | 1000 | `SEED_MODE=reseed` |

The globe draws 50 of whichever file was seeded, unless `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT` is `0` or another cap. The written target for the full dump is about 1,000. Re-run `--write-seed` only if the demo needs that set. After a reseed, the API count and the file count should match:

```bash
python3 -c "import json; print(len(json.load(open('data/seed/mountains.json'))))"
curl -s http://localhost:8000/mountains | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
```

---

## Trail routes (Rainier only today)

### What the user sees

- **`GET /mountains/mount-rainier`** returns **trails**, **mile segments**, hazard, etc.
- Other slugs return **mountain metadata only** (empty `trails[]`) unless you import trails for that bbox.

### Source (no runtime trail API)

| File | Loaded by | Notes |
|------|-----------|--------|
| `data/seed/trails.geojson` | `backend/app/seed.py` | **67** OSM/Overture lines for Rainier |
| `data/seed/trail_segments.geojson` | same | Hero trail (Skyline) **0.1 mi** segments |
| `data/seed/trail_network.geojson` | `backend/app/bypass.py` | Walkable network for bypass routing |

Produced offline by **`ml/scripts/import_trails.py`** and **`ml/scripts/build_trail_network.py`** (OpenStreetMap / Overture—not Overpass at API time).

| Operation | When | Speed (typical) |
|-----------|------|-----------------|
| `python -m app.seed` (trails + segments) | Setup / deploy | **1–3 s** for trail tables |
| Re-import trails for a new mountain | New ML/data step per bbox | **Minutes** (download + process; not built for arbitrary globe clicks) |

**Do not use an LLM** for trail geometry or names. Agents **read** trail facts from Postgres/tools after import.

---

## Related API surface (not catalog)

| Endpoint | External calls? |
|----------|-----------------|
| `GET /mountains`, `GET /mountains/{slug}` | No (Postgres + seed files) |
| `POST /mountains/{slug}/analyze`, run stream | Open-Meteo once per run; LLM per agent |
| `GET /mountains/{slug}/layers/*` | No (local tiles); live mountains only |
| `GET /forecast`, advisory routes | No (Postgres after a run) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Globe shows **2–3** pins | DB seeded from old **3-row** `mountains.json` | Finish `--write-seed`, `app.seed`, restart API |
| Pins cluster at the **poles** (Antarctica/Patagonia, ~0 in NH) | Whole-band Overpass queries timed out on the dense northern bands and returned empty | Fixed: **tiled** queries (lat × lon) + even band quotas; re-run `--write-seed` |
| `--write-seed` wrote **1** peak | Overpass used `out tags` (no coordinates) | Fixed: use **`out body`**; re-run with `--source overpass` |
| `--write-seed` aborts with “fewer than 500 rows” | Most tiles failed (Overpass overloaded) | Check the per-tile logs, wait, re-run; the committed seed was not touched |
| Wikidata **429** | Rate limit | Use **`--source overpass`** for bulk seed; ignore Wikidata for hackathon |
| Click peak, empty trails | Catalog peak, not Rainier | Expected until trail import exists for that mountain |
| Analyze fails on Fuji | `is_live: false` | Expected; only Rainier runs the pipeline |

---

## Files to know

| Path | Role |
|------|------|
| `data/seed/mountains.json` | Committed peak catalog |
| `backend/app/mountain_catalog.py` | Offline fetch + DB load from JSON only at runtime |
| `backend/app/seed.py` | Loads all seed files into Postgres |
| `ml/scripts/import_trails.py` | Offline Rainier trail import |
| `context/docs/CODE_REFERENCE.md` | File map (update when adding scripts) |
