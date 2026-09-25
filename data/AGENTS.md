# Data agent guide

Files only. No code runs in this folder. Track: ML and data.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## What lives where

| Path | In git | What |
|---|---|---|
| `seed/` | Yes | Small JSON and GeoJSON the API loads, plus `sources.md` |
| `raw/` | No | Downloads such as the DEM and land cover. Recreate them with `ml/scripts/download_sources.py` |
| `processed/` | No | Derived rasters and the feature table |

## Seed files

| File | Step | Loaded by |
|---|---|---|
| `seed/mountains.json` | 5 | `backend/app/seed.py` |
| `seed/trails.geojson` | 5, replaced in 14 | `backend/app/seed.py` |
| `seed/landslides.geojson` | 10, used in 14 | Map pins and model labels |
| `seed/sources.md` | 10 | People. One entry per downloaded file |

## Rules

- Keep each seed file small and readable. Large data belongs in `raw/` or `processed/`.
- GeoJSON coordinates are `[lon, lat]` in WGS84.
- Risk values use the shared vocabulary: `low`, `moderate`, `high`, `extreme`.
- Every downloaded file gets a `sources.md` entry with its URL and access date.
- Seed changes that alter a field name are contract changes. Update `backend/app/seed.py` in the same commit.
