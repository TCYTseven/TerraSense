# Data agent guide

Files only. No code runs in this folder. Track: ML and data.

Read the repo root [`AGENTS.md`](../AGENTS.md) first for the team rules and shared facts.

## What lives where

| Path | In git | What |
|---|---|---|
| `seed/` | Yes | Small JSON and GeoJSON the API loads, plus `sources.md` |
| `raw/` | No | Downloads such as the DEM and land cover. Recreate them with `ml/scripts/download_sources.py`; the regional `region_dem_cop30.tif` and `region_landcover_worldcover2021.tif` with `ml/scripts/download_region.py`. The USGS v3 inventory CSVs sit in `raw/usgs_v3/` |
| `processed/` | No | Derived rasters and feature tables: the legacy `features.tif`/`features.parquet`, the regional `regional_labels.parquet` (+ `regional_labels_summary.json`) and `rainier_regional_features.tif` (17 bands on the Rainier grid), plus event-time `risk_samples.parquet` and `landslide_risk.parquet`. Rebuild with the scripts in `ml/scripts/`. |

## Seed files

| File | Step | Loaded by |
|---|---|---|
| `seed/mountains_test.json` | 5 | Catalog when `SEED_MODE=mountainstest` (the default). ~140 named peaks spaced across the Americas, Europe, Africa, and Asia, plus Mount Rainier. |
| `seed/mountains.json` | 5 | Full Overpass catalog. Regenerated offline: `python -m app.mountain_catalog --write-seed --source overpass` from `backend/`. Loaded when `SEED_MODE=reseed`. Reseeding removes static mountains the active file no longer lists. |
| `seed/satellite_images.json` | 5 | `backend/app/seed.py`, into `mountain_satellite_images`. One Esri World Imagery preview per catalog mountain, keyed by `mountain_slug`. |
| `seed/trails.geojson` | 5, replaced in 14 | `backend/app/seed.py`. Written by `ml/scripts/import_trails.py` |
| `seed/trail_segments.geojson` | 14 | `backend/app/seed.py`. Written by `ml/scripts/import_trails.py` |
| `seed/trail_network.geojson` | 19 | `backend/app/bypass.py`. Written by `ml/scripts/build_trail_network.py` |
| `seed/landslides.geojson` | 10, used in 14 | Historical map pins and a source catalog. The event-time builder applies dated rainfall-trigger filters before using records as 72-hour labels. See `seed/sources.md` |
| `seed/sources.md` | 10 | People. One entry per downloaded file |
| `seed/hills.json` | 38 | `backend/app/seed.py` `load_hills`. Turtle Mountain stays live. The other rows are static hill and cliff markers (`is_live` false), the same pattern as the mountain catalog, written by `ml/scripts/build_hill_catalog.py`. A mountain reseed does not drop them. |
| `seed/packs/index.json` | 32 | `backend/app/packs.py`. Written by `python ml/scripts/mountain_packs.py --write-index`: one row per pack (name, peak, bbox, UTM zone, hero trail or null) |
| `seed/packs/<slug>/…` | 32 | One folder per demo peak with the same four files in the same formats: `trails.geojson`, `trail_segments.geojson`, `trail_network.geojson`, `landslides.geojson` (may be an empty collection). Written by `python ml/scripts/build_pack.py <slug>` |

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
| `is_live` | boolean | `true` for Rainier and for Turtle Mountain. Other catalog peaks and hills stay false |
| `kind` | string | Omitted from the catalog JSON. The database default is `mountain`. `hills.json` rows are `hill` |

The two static peaks, Huascarán (`high`) and Mount Fuji (`low`), are globe markers. Their risk values are display placeholders picked to show the color range. They are not assessments.

Static hills use the same placeholder field. The color comes from recorded NASA Global Landslide Catalog fatalities within 10 km of the site: none is `low`, 1–19 is `moderate`, 20–99 is `high`, and 100 or more is `extreme`. That is a catalog color, not a model score. Only Turtle Mountain has a scored window.

Every static hill is pinned to a Wikidata item and has a documented landslide or rockfall record. `ml/scripts/build_hill_catalog.py` holds that list, checks each item against its OpenStreetMap summit or cliff, and writes the rows, the trail files, the hill rows of `seed/satellite_images.json`, and the table under Static hills in `seed/sources.md`. Add or drop a hill there and rerun it; do not hand-edit a static row. A place that is only an OpenStreetMap point, a pass, a gorge, or a building is not a hill.

The script refuses a hill, and writes nothing, when its Wikidata item is not typed as a landform (`LANDFORM_TYPES`: hill, mountain, cliff, volcano, and the like; an untyped item passes only when its OSM feature is a landform), when its OSM feature sits over 3 km from the item, or when a catalog mountain is within 5 km (the globe already marks that place). A record is either written by hand with the source it was checked against, or left out, in which case the script writes it from the deadliest NASA catalog event within 5 km, placed to 5 km or better, and states the distance and accuracy. A hill with neither is refused. Catalog rows whose fatality count contradicts their own description are corrected in `GLC_FATALITY_FIXES`.

Named paths for a hill, when OpenStreetMap has them, live in `seed/hills/<slug>/trails.geojson` and load with the pack trail files: named foot ways and walking-route relations within 1.5 km of the point, cut to 2.5 km, up to 12, closest first. Each line starts at its lower end on the Terrarium tiles, and `elevation_gain_m` is the climb along it. Hills with no named path have no trail file.

`seed/satellite_images.json` is a list, one entry per mountain in the active catalog:

| Field | Type | Notes |
|---|---|---|
| `mountain_slug` | string | Upsert key. Must be a slug in the catalog file |
| `mountain_name` | string | Display name, same as the catalog |
| `image_url` | string | Fetchable image endpoint. Today an Esri World Imagery `export` URL for the peak's box |
| `file_path` | string or null | Where a downloaded copy belongs, relative to the repo root |
| `file_ext` | string or null | `jpg` |
| `source` | string or null | Attribution, e.g. `Esri World Imagery` |
| `download_status` | string | `downloaded`, `pending`, or `error` |
| `bbox` | `[west, south, east, north]` | WGS84, the box the image covers |
| `image_size_px` | integer or null | Square side in pixels |
| `error` | string or null | Why a `pending` or `error` row has no image |

`seed/trails.geojson` is a FeatureCollection of LineStrings, one feature per line of the file. Each feature's properties: `mountain_slug`, `name`, `length_km`, `elevation_gain_m`, `source` (attribution), and an optional `note`. A line starts at its lower end, so `elevation_gain_m` is the climb walking it uphill. The hero trail is the exception: a loop from its trailhead. The seed removes a mountain's trails that are no longer in the file. The lines come from OpenStreetMap, so the file is ODbL: keep "© OpenStreetMap contributors" wherever it is shown.

`seed/trail_segments.geojson` is a FeatureCollection of LineStrings: the hero trail, cut in order. Each feature's properties: `mountain_slug`, `trail` (a name in `trails.geojson`), `seq` (0, 1, 2, ... with no gaps), `start_mile`, `end_mile`. The trail with segments is the one the model scores mile by mile. Rainier's is the Skyline Trail, every 0.1 mile from the Paradise trailhead; a pack's default hero is the longest named hiking trail in its box (valley rail trails and greenways are skipped), or the hero its registry entry pins (Everest Base Camp Trek, Tuckerman Ravine Trail on Mount Washington), mile 0 at the lower trailhead.

`seed/trail_network.geojson` is a FeatureCollection of LineStrings with `[lon, lat, elevation m]` vertices: the walkable network the bypass routes on. The header names `hero_trail` and `hero_length_mi`. Loop pieces have `hero: true`, `trail`, `from_mile`, `to_mile`, and `length_m`, cut at every junction from the same line as the mile segments. Other edges have `hero: false`, `trail` (null when OpenStreetMap has no name), `class`, and `length_m`. Edges meet only at shared vertices. It is derived from OpenStreetMap, so it is ODbL like `trails.geojson`.

## Rules

- Keep each seed file small and readable. Large data belongs in `raw/` or `processed/`.
- GeoJSON coordinates are `[lon, lat]` in WGS84.
- Risk values use the shared vocabulary: `low`, `moderate`, `high`, `extreme`.
- Every downloaded file gets a `sources.md` entry with its URL and access date.
- Seed changes that alter a field name are contract changes. Update `backend/app/seed.py` in the same commit.
