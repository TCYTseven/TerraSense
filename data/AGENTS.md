# Data agent guide

Files only. No code runs in this folder. Track: ML and data.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## What lives where

| Path | In git | What |
|---|---|---|
| `seed/` | Yes | Small JSON and GeoJSON the API loads, plus `sources.md` |
| `raw/` | No | Downloads such as the DEM and land cover. Recreate them with `ml/scripts/download_sources.py` |
| `processed/` | No | Derived rasters and the feature table: `features.tif` (7-band stack on the 30 m UTM grid) and `features.parquet` (labeled sample). Rebuild with `ml/scripts/build_features.py` |

## Seed files

| File | Step | Loaded by |
|---|---|---|
| `seed/mountains.json` | 5 | `backend/app/seed.py`. Committed catalog (~1000 peaks). Regenerate offline: `python -m app.mountain_catalog --write-seed --source overpass` from `backend/`. The API does not fetch externally at runtime. |
| `seed/trails.geojson` | 5, replaced in 14 | `backend/app/seed.py`. Written by `ml/scripts/import_trails.py` |
| `seed/trail_segments.geojson` | 14 | `backend/app/seed.py`. Written by `ml/scripts/import_trails.py` |
| `seed/trail_network.geojson` | 19 | `backend/app/bypass.py`. Written by `ml/scripts/build_trail_network.py` |
| `seed/landslides.geojson` | 10, used in 14 | Map pins and model labels. Pending: data.nasa.gov was unreachable from the build container. See `seed/sources.md` |
| `seed/sources.md` | 10 | People. One entry per downloaded file |

## Seed formats

`seed/mountains.json` is a list. Each entry:

| Field | Type | Notes |
|---|---|---|
| `name` | string | Display name. UTF-8, accents allowed |
| `slug` | string | URL key and upsert key. Rainier is `mount-rainier` |
| `lat`, `lon` | number | Summit, WGS84 |
| `elevation_m` | integer | Summit elevation |
| `region` | string | Shown under the name |
| `current_risk_level` | string | Placeholder until the first real analysis. Static mountains keep it for good |
| `is_live` | boolean | `true` only for Rainier |

The two static peaks, Huascarán (`high`) and Mount Fuji (`low`), are globe markers. Their risk values are display placeholders picked to show the color range. They are not assessments.

`seed/trails.geojson` is a FeatureCollection of LineStrings, one feature per line of the file. Each feature's properties: `mountain_slug`, `name`, `length_km`, `elevation_gain_m`, `source` (attribution), and an optional `note`. A line starts at its lower end, so `elevation_gain_m` is the climb walking it uphill. The hero trail is the exception: a loop from its trailhead. The seed removes a mountain's trails that are no longer in the file. The lines come from OpenStreetMap, so the file is ODbL: keep "© OpenStreetMap contributors" wherever it is shown.

`seed/trail_segments.geojson` is a FeatureCollection of LineStrings: the hero trail, cut in order. Each feature's properties: `mountain_slug`, `trail` (a name in `trails.geojson`), `seq` (0, 1, 2, ... with no gaps), `start_mile`, `end_mile`. The trail with segments is the one the model scores mile by mile. Today that is Rainier's Skyline Trail, every 0.1 mile from the Paradise trailhead.

`seed/trail_network.geojson` is a FeatureCollection of LineStrings with `[lon, lat, elevation m]` vertices: the walkable network the bypass routes on. The header names `hero_trail` and `hero_length_mi`. Loop pieces have `hero: true`, `trail`, `from_mile`, `to_mile`, and `length_m`, cut at every junction from the same line as the mile segments. Other edges have `hero: false`, `trail` (null when OpenStreetMap has no name), `class`, and `length_m`. Edges meet only at shared vertices. It is derived from OpenStreetMap, so it is ODbL like `trails.geojson`.

## Rules

- Keep each seed file small and readable. Large data belongs in `raw/` or `processed/`.
- GeoJSON coordinates are `[lon, lat]` in WGS84.
- Risk values use the shared vocabulary: `low`, `moderate`, `high`, `extreme`.
- Every downloaded file gets a `sources.md` entry with its URL and access date.
- Seed changes that alter a field name are contract changes. Update `backend/app/seed.py` in the same commit.
