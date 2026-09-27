# Data sources

Step 10 source layers for Mount Rainier. `ml/scripts/download_sources.py` produces every file below. Run it from the repo root:

```bash
python ml/scripts/download_sources.py [--only dem,landcover,landslides] [--force] [--glc-csv URL_OR_PATH]
```

Every layer uses the shared bounding box `[-121.93, 46.76, -121.54, 46.96]` (EPSG:4326, west, south, east, north). Rasters keep their native EPSG:4326 grid, and step 11 resamples them to one 30 m grid. `data/raw/` is gitignored, so rerun the script to rebuild it.

| File | Source | Accessed | Status |
|---|---|---|---|
| `data/raw/rainier_dem_cop30.tif` | Copernicus DEM GLO-30 | 2026-09-25 | Done |
| `data/raw/rainier_landcover_worldcover2021.tif` | ESA WorldCover 2021 v200 | 2026-09-25 | Done |
| `data/raw/coolr/global_landslide_catalog_export.csv` | NASA COOLR / Global Landslide Catalog current static CSV export | 2026-09-26 | Done. 8.1 MB |
| `data/raw/usgs_v3/US_Landslide_v3_csv.zip` | USGS Landslide Inventories across the United States v3 CSV archive | 2026-09-26 | Done. MD5 `6262364ad05e05e683573fd58e4d6e27` |
| `data/raw/soilgrids/soilgrids_*_{0-5,5-15,15-30,30-60}cm_mean.tif` | ISRIC SoilGrids 2.0 WCS: clay, sand, silt, bulk density, coarse fragments, soil organic carbon | 2026-09-26 | Done. 24 Rainier-bbox subsets at 0.002° output resolution |
| `data/raw/noaa/gfs/*.grib2` | NOAA/NCEP GFS 0.25° NOMADS subsets, 2026-09-25 00Z, f000–f072 | 2026-09-26 | Done. 13 Rainier-area forecast files |
| `data/raw/noaa/gefs/*.grib2` | NOAA/NCEP GEFS 0.25° NOMADS control, ensemble mean, and spread, 2026-09-25 00Z, f000–f072 | 2026-09-26 | Done. 39 Rainier-area forecast files |
| `data/raw/osm/washington-latest.osm.pbf` | Geofabrik OpenStreetMap Washington extract | 2026-09-26 | Done. MD5 `4279177b98c6c2dabd0c6f2022cff20a`, 363,627,224 bytes |
| `data/raw/avalanche/nwac/*.json` | Northwest Avalanche Center / National Avalanche Center public observation API, Rainier bbox, 2023-12-01 through 2026-09-26 | 2026-09-26 | Done. 81 avalanche records and 281 field observations; raw pages plus `manifest.json` |
| `data/raw/avalanche/regional_nwac/*.json` | National Avalanche Center / Avalanche.org public observation API, bounded Northwest bbox `-125,42,-116,49.1`, 2023-10-25 through 2026-07-20 | 2026-09-26 | Done. 1,282 avalanche observations and 6,255 in-range field observations after excluding 329 out-of-window records; audit corpus only until regional static/weather features are joined |
| `data/raw/avalanche/caic/*.json` | Colorado Avalanche Information Center official public Avalanche Explorer observation and field-report API | 2026-09-26 | Done. 25,561 historical avalanche observations; optional controls query is reproducible with `--include-controls`; audit-only until regional terrain and as-of forecast joins are implemented |
| `data/raw/landslide/washington_wgs/*.geojson` | Washington Geological Survey Recent Landslides layer 1 | 2026-09-26 | Done. 742 records, 15 exact-date records; no rainfall-trigger field, so retained as audit-only and excluded from 72-hour rainfall labels |
| `data/raw/avalanche/weather/openmeteo_*.json` | Open-Meteo historical hourly weather archive for a Rainier-area grid point | 2026-09-26 | Done. Retrospective observed/reanalysis weather proxy only; not historical NOAA forecasts |
| `data/raw/avalanche/snotel/paradise_679_*.html` | NRCS AWDB Report Generator, Paradise (679:WA:SNTL) hourly SWE/snow depth/precipitation/temperature | 2026-09-26 | Done. 23,959 parsed rows; station-level snowpack proxy, provisional data |
| `data/seed/landslides.geojson` | NASA Global Landslide Catalog local export, supplemented by Washington State Landslide Inventory Database — Landslide Compilation | 2026-09-26 | Done. 37 mapped events total: 4 NASA events (1 at 1km accuracy, 3 at 5km) plus 33 supplemental 1km inventory points |
| `data/seed/trails.geojson`, `data/seed/trail_segments.geojson` | OpenStreetMap via Overture Maps | 2026-09-25 | Done. Written by `ml/scripts/import_trails.py` |
| `data/seed/hills.json`, `data/seed/hills/<slug>/trails.geojson` | Wikidata items, OpenStreetMap via the Overpass API (named paths and walking-route relations within 1.5 km), NASA Global Landslide Catalog | 2026-09-26 | Static hills rebuilt by `ml/scripts/build_hill_catalog.py`; see Static hills below. Turtle Mountain's row and trails are unchanged. ODbL for the paths |
| `data/seed/trail_network.geojson` | Derived from the two above and the DEM | 2026-09-25 | Done. Written by `ml/scripts/build_trail_network.py` |

## Elevation: `data/raw/rainier_dem_cop30.tif`

- **Source:** Copernicus DEM GLO-30, tile `Copernicus_DSM_COG_10_N46_00_W122_00_DEM`, from the AWS Open Data bucket.
- **URL:** https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N46_00_W122_00_DEM/Copernicus_DSM_COG_10_N46_00_W122_00_DEM.tif
- **Dataset page:** https://registry.opendata.aws/copernicus-dem/
- **Licence:** Copernicus DEM licence. Attribution: "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved".
- **Grid:** 1405 x 721 px at 1 arcsec, about 21 m east-west by 31 m north-south here. float32 meters, no nodata, no voids in the box. Bounds `(-121.930139, 46.759861, -121.539861, 46.960139)`: the window grows outward to whole pixels.
- **Heights:** meters above the EGM2008 geoid. This is a surface model from 2011 to 2015 radar, so it includes tree canopy and glacier ice.
- **Check:** 665.1 m to 4414.6 m. The highest pixel is 22.6 m above the shared 4392 m summit because the summit ice cap is noisy in this model. Display the shared 4392 m.

## Land cover: `data/raw/rainier_landcover_worldcover2021.tif`

- **Source:** ESA WorldCover 10 m 2021 v200, tile `N45W123`, from the AWS Open Data bucket. The script reads only the box window, never the full 65 MB tile.
- **URL:** https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N45W123_Map.tif
- **Dataset page:** https://esa-worldcover.org
- **Licence:** CC BY 4.0. Attribution: "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium". Citation: Zanaga, D. et al. (2022), ESA WorldCover 10 m 2021 v200, https://doi.org/10.5281/zenodo.7254221
- **Grid:** 4680 x 2400 px at 1/12000 degree, about 6.3 m by 9.3 m here. uint8 class codes, nodata 0. Bounds match the box exactly.
- **Classes:** 10 Tree cover, 20 Shrubland, 30 Grassland, 40 Cropland, 50 Built-up, 60 Bare/sparse vegetation, 70 Snow and ice, 80 Permanent water bodies, 90 Herbaceous wetland, 95 Mangroves, 100 Moss and lichen. These are categories: resample with nearest neighbour or mode, never bilinear.
- **Check:** tree cover 59.8%, snow and ice 15.0%, bare/sparse vegetation 11.7%, grassland 11.0%, moss and lichen 1.8%, water 0.6%, shrubland and built-up under 0.1% each.

## Landslide points: `data/seed/landslides.geojson`

- **Status:** refreshed from the supplied NASA Global Landslide Catalog export on 2026-09-26. NASA has four events in the Rainier box, but only one is precise enough for 30 m pixel labels; the official Washington inventory supplements it with 33 conservative 1km representative points so the spatial split has enough positive regions. No point was placed by hand.
- **Primary source:** NASA COOLR / Global Landslide Catalog, "Global Landslide Catalog Export". CSV: https://data.nasa.gov/docs/legacy/Global_Landslide_Catalog_Export/Global_Landslide_Catalog_Export_rows.csv. Local cache: `data/raw/coolr/global_landslide_catalog_export.csv`. Local refresh command: `python ml/scripts/download_sources.py --only landslides --glc-csv data/raw/coolr/global_landslide_catalog_export.csv --force`.
- **Supplemental source:** Washington Geological Survey, Washington State Landslide Inventory Database, **Landslide Compilation** layer 131. URL: https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/131
- **Query URL:** https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/131/query
- **Licence/attribution:** Washington Geological Survey; retain the source URL and inventory name with the derived seed. The layer warns that mapped coverage and confidence vary by source and scale; its representative points are conservatively labeled `location_accuracy: 1km` for training.
- **Output:** a FeatureCollection of 37 Points inside the box, oldest first. NASA points preserve their catalog accuracy (`1km` or `5km`); polygon features are clipped to the bbox and converted to interior representative points with conservative `1km` accuracy. Step 11 uses only `exact` and `1km` points, yielding 34 usable training points. Properties: `id`, `date` (ISO or null), `title`, `category`, `trigger`, `size`, `setting`, `location_accuracy`, `fatalities`, `source_name`, `source_link`, `catalog`, `inventory_confidence`, `source_layer`.

**To refresh.** On a network that reaches data.nasa.gov, run `python ml/scripts/download_sources.py --only landslides`. If NASA is unavailable, the script automatically queries the Washington fallback. To use a downloaded NASA CSV explicitly, run `python ml/scripts/download_sources.py --only landslides --glc-csv path/to/export.csv`; sparse high-accuracy NASA results are supplemented with the Washington inventory.

**For step 11.** The catalog geocodes events from news reports, so `location_accuracy` runs from `exact` to `50km`, and the box may hold only a few events. Keep `exact` and `1km` points for pixel labels. The fetched USGS v3 CSV archive is at `data/raw/usgs_v3/US_Landslide_v3_csv/` and contains `us_ls_v3_point.csv` and `us_ls_v3_poly.csv`; source release: https://www.usgs.gov/data/landslide-inventories-across-united-states-ver-30-february-2025.

## Production risk-source cache

The following files are fetched for the event-time 72-hour classifier. They are all ignored by Git and are spatially scoped to the shared Rainier study area unless noted otherwise.

- **NASA GLC:** current static CSV export above; the retired Socrata endpoint is not used.
- **USGS v3:** official ScienceBase release `https://www.sciencebase.gov/catalog/item/671eef1fd34ed0f827ea9f12`, CSV archive `US_Landslide_v3_csv.zip`.
- **SoilGrids 2.0:** WCS endpoint `https://maps.isric.org/mapserv`; each subset uses `SUBSETTINGCRS=EPSG:4326`, `OUTPUTCRS=EPSG:4326`, `X(-121.93,-121.54)`, `Y(46.76,46.96)`, and `RESX=RESY=0.002`. Coverage families are `clay`, `sand`, `silt`, `bdod`, `cfvo`, and `soc`, each at `0-5cm`, `5-15cm`, `15-30cm`, and `30-60cm` with the mean prediction.
- **NOAA GFS:** NOMADS filter endpoint `https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl`; run directory `/gfs.20260925/00/atmos`, forecast files f000 through f072 at six-hour intervals. Requested fields are precipitation, precipitation rate, 2 m temperature, snow depth, snow water equivalent, and top-layer soil water where available.
- **NOAA GEFS:** NOMADS filter endpoint `https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl`; run directory `/gefs.20260925/00/atmos/pgrb2sp25`, with control (`gec00`), ensemble mean (`geavg`), and spread (`gespr`) at f000 through f072.
- **NOAA GEFS historical forecasts:** the public AWS Open Data bucket `s3://noaa-gefs-pds`, documented at `https://registry.opendata.aws/noaa-gefs/`. `ml/scripts/download_noaa_historical_forecasts.py` reads the dated `geavg`/`gespr` 0.25-degree GRIB2 products and their `.idx` files, then uses HTTP byte ranges to extract only Rainier-cell messages. The as-of cycle is the latest 6-hour GEFS run at least six hours before the reference time; no future-initialized run is allowed. The completed 2026-09-26 run retrieved precipitation, snow-water-equivalent, temperature, and wind fields for 119 references and 52 cells with zero failed reference/lead groups. The output is an ignored parquet feature table plus a manifest.
- **OpenStreetMap / Geofabrik:** `https://download.geofabrik.de/north-america/us/washington-latest.osm.pbf`; the current Washington extract is retained because Geofabrik distributes it as a regional PBF, not a Rainier-only file. Use a PBF-aware extractor to clip roads around the bbox.

## Trails: `data/seed/trails.geojson` and `data/seed/trail_segments.geojson`

- **Source:** OpenStreetMap foot paths, read from the Overture Maps Foundation transportation theme, release `2026-09-23.0` (OSM snapshot 2026-09-09). Overpass and Geofabrik were unreachable from the build container; the Overture bucket needs no key.
- **URL:** s3://overturemaps-us-west-2/release/2026-09-23.0/theme=transportation/type=segment/ (also https://overturemaps-us-west-2.s3.amazonaws.com/release/2026-09-23.0/theme=transportation/type=segment/). The script reads only the Parquet row groups whose bbox statistics overlap the box: about 317 MB of the 72 GB theme, 15 s here.
- **Licence:** ODbL 1.0. Attribution: "© OpenStreetMap contributors". Overture adds "Overture Maps Foundation". The seed files are a derived database, so they stay ODbL.
- **Selection:** walkable classes (footway, path, steps, track) in the box, clipped to it: 517 segments. Merged by name, then left out: names under 200 m, forest roads (track only), and the four summit climbing routes. 67 trails remain.
- **Hero trail:** the NPS Skyline loop, OpenStreetMap's "Skyline Trail" and "Upper Skyline Trail" joined, from the Paradise trailhead (46.78650, -121.73652), clockwise. 8.87 km (5.51 mi) and 560 m of gain after 5 m simplification. The park gives 5.5 mi and 1,700 ft (518 m). Cut every 0.1 mile into 55 segments.
- **Heights:** gain comes from the Copernicus DEM above, sampled every 30 m. It is a surface model, so forest trails read a few percent high.
- **Rerun:** `python ml/scripts/import_trails.py` (add `--force` to read Overture again). The bucket keeps only recent releases; if `2026-09-23.0` is gone, the script lists the ones available.

## Trail network: `data/seed/trail_network.geojson`

- **Source:** derived, no new download. The walkable OpenStreetMap segments cached by step 14 (`data/raw/rainier_trail_segments.geojson`, Overture release `2026-09-23.0`), elevations from the Copernicus DEM above.
- **Licence:** ODbL 1.0, as a derived database of OpenStreetMap. Attribution: "© OpenStreetMap contributors".
- **Contents:** the Skyline loop cut at its 24 junctions (from the same simplified line as the mile segments), plus the 114 walkable edges within 2.5 km of the loop that connect to it (34 km). Vertices every 30 m or closer carry the DEM elevation, so the bypass can report added climb.
- **Rerun:** `python ml/scripts/build_trail_network.py` after `import_trails.py`.

## Regional susceptibility and Model B validation (Sep 26)

Gitignored. Recreate with the scripts named here.

- **Regional DEM and land cover:** `data/raw/region_dem_cop30.tif` and `data/raw/region_landcover_worldcover2021.tif`, bbox `[-122.6, 46.4, -121.2, 47.5]` plus a margin. Copernicus DEM GLO-30 COGs from `https://copernicus-dem-30m.s3.amazonaws.com/` and ESA WorldCover 2021 v200 from `https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/`. Fetched 2026-09-26 by `python ml/scripts/download_region.py`.
- **Landslide labels:** USGS Landslide Inventories across the United States v3 (doi:10.5066/P14AJF8I), Washington Geological Survey records at confidence 3 or higher. Read from `data/raw/usgs_v3/` by `ml/scripts/build_regional_features.py` and `ml/scripts/event_catalog.py`.
- **Historical rain:** Open-Meteo historical weather API (`https://archive-api.open-meteo.com/v1/archive`, ERA5 reanalysis), daily totals for each dated event cell, 1980–2023. Cached in `data/raw/open_meteo_archive/` (62 MB) by `python ml/scripts/event_rain.py`. Open-Meteo data is CC BY 4.0.

## Mountain packs (step 32): mount-washington, kilimanjaro, mount-everest, mount-erebus, mount-kailash

One Rainier-style bundle per demo peak, built 2026-09-26 by `python ml/scripts/build_pack.py <slug>`. Rasters and tiles are gitignored and rebuild from that one command; the committed seeds live in `data/seed/packs/<slug>/`, the tiles under `backend/tiles/<slug>/susceptibility/`.

- **DEM:** Copernicus DEM GLO-30 COGs from `https://copernicus-dem-30m.s3.amazonaws.com/`, the 1x1 degree tiles each bbox touches, window-read and mosaicked. Licence and attribution as the Rainier DEM entry above. Tiles: mount-washington `N44_00_W072`; kilimanjaro `S04_00_E037`, `S03_00_E037`; mount-everest `N27_00_E086`, `N27_00_E087`, `N28_00_E086`, `N28_00_E087`; mount-erebus `S78_00_E165` through `S78_00_E168`; mount-kailash `N30_00_E081`, `N31_00_E081`. Check: the highest pixel sits within 9 m of the shared peak everywhere but Everest (-111.2 m, the GLO-30 snow surface at the summit) and Kailash (-189.4 m: the GLO-30 surface peaks at 6448.6 m, 90 m from the cited 6638 m summit, so the catalog elevation is the published figure, not the DEM's).
- **Land cover:** ESA WorldCover 2021 v200 windows from `https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/`: mount-washington `N42W072`; kilimanjaro `S06E036`, `S03E036`; mount-everest `N27E084`, `N27E087`; mount-kailash `N30E081`. Licence as the Rainier entry. **mount-erebus downloads nothing:** WorldCover maps nothing south of 60 deg S, so `download_sources.py` writes a synthetic raster on the DEM's grid — class 70 (snow and ice) everywhere except sea-level DEM cells, which carry class 80 (water) so the index zeroes McMurdo Sound. 55.1% ice, 44.9% water.
- **Landslides:** the cached NASA GLC export above, filtered to each bbox. mount-washington holds 1 event (GLC 5732, a 2013 snow avalanche); the other four boxes hold none and their records start honestly empty.
- **Trails:** OpenStreetMap foot paths via the Overture Maps transportation theme, release `2026-09-23.0` (same URL and ODbL terms as the Rainier trails entry), windowed parquet reads per bbox. kilimanjaro and mount-everest additionally read OSM walking-route relations from Overpass (`https://overpass-api.de/api/interpreter`, accessed 2026-09-26) because their trek names live on route relations over nameless ways; the payloads are cached in `data/raw/packs/<slug>/route_relations.json`. mount-kailash needed no Overpass call: its three trails carry OSM way names directly, the longest being the 46.3 km pilgrim circuit `冈仁波齐转山` (the Kailash Kora), which becomes its hero. Relation names are OSM data, so the derived seeds stay ODbL with the same attribution.

## Turtle Mountain (hill)

The first hill. Crowsnest Pass, Alberta, Canada (Blairmore Range, NTS 82G/9). This is the Frank Slide site. Turtle Mountain in Manitoba is a different place.

- **Summit.** 49.57694, -114.41222. Elevation 2210 m. Wikipedia, "Turtle Mountain (Alberta)", read 2026-09-26. https://en.wikipedia.org/wiki/Turtle_Mountain_(Alberta)
- **Frank Slide point.** 49.59111, -114.39528. 29 April 1903. Wikipedia, "Frank Slide", read 2026-09-26. https://en.wikipedia.org/wiki/Frank_Slide
- **Bounding box.** `[-114.48, 49.54, -114.34, 49.64]` (west, south, east, north). Drawn so both points sit inside: about 5 km west of the summit and about 4 km east of the slide point. No slide volume is used. Published volumes disagree, and none is shown in the app.
- **Terrain window.** `python ml/scripts/build_hill_window.py` reads a margin of 0.05° around the box, builds `data/processed/hills/turtle-mountain/features.tif` on a 30 m grid in EPSG:32611, applies the existing regional LightGBM (no retrain), and writes `ml/artifacts/hills/turtle-mountain/susceptibility.tif` and `probability.tif`. Those files are gitignored. Rainier's rasters are not replaced. Washington AUC is not this hill's accuracy. The Frank Slide was a rockslide; Model B's rain trigger is not an explanation of 1903.
- **DEM.** Copernicus DEM GLO-30, tile `Copernicus_DSM_COG_10_N49_00_W115_00_DEM`. Accessed 2026-09-26. https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N49_00_W115_00_DEM/Copernicus_DSM_COG_10_N49_00_W115_00_DEM.tif
- **Land cover.** ESA WorldCover 10 m 2021 v200, tile `N48W117`. Accessed 2026-09-26. https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W117_Map.tif
- **Rain.** Open-Meteo at the summit (49.57694, -114.41222), the same feed Model B uses on Rainier. Fetched when the window is scored, not stored.

## Static hills

The static hill and cliff markers in `data/seed/hills.json` (every row but Turtle Mountain) and their paths in `data/seed/hills/<slug>/trails.geojson`. Rebuilt Sep 26, 2026 by `python ml/scripts/build_hill_catalog.py`, which replaced an earlier list whose rows were unnamed or mislabeled OpenStreetMap points (a gorge, a road pass, a locality, and a point called "Battery" among them).

- **Identity.** Wikidata `wbgetentities`, https://www.wikidata.org/w/api.php, accessed 2026-09-26. Each hill is pinned to one item by its QID and must be typed (P31) as a landform; its coordinates and elevation (property P2044) come from there. Cached at `data/raw/hills/wikidata.json`. CC0.
- **Records.** A written record cites the page it was checked against in the table below. A hill without one takes its record from the NASA Global Landslide Catalog: the deadliest event within 5 km placed to 5 km or better, with the distance and accuracy in the sentence. Candidates beyond the hand-picked list were found by asking Wikipedia's GeoSearch API (https://en.wikipedia.org/w/api.php, plus es, pt, it, fr, and de where the country speaks them) for landform articles within 3 km of catalog events placed to 5 km or better, then keeping items whose Wikidata type is a landform, that have a Wikipedia article outside the bot-generated wikis, and that have a catalog event within 3 km placed to 1 km or better. Accessed 2026-09-26.
- **Summit and paths.** OpenStreetMap via the Overpass API (https://overpass-api.de/api/interpreter and mirrors), accessed 2026-09-26. The summit is the OSM node that carries the item's `wikidata` tag when there is one (for an item with no Wikidata type, else a landform of the same name within 3 km), otherwise the Wikidata point moved to the highest Terrarium ground within 400 m. Paths are named `path`, `footway`, `track`, `bridleway`, and `steps` ways plus `route=hiking|foot|walking` relations within 1.5 km, cut to 2.5 km, oriented from the lower end on the Terrarium tiles. Cached at `data/raw/hills/<slug>/`. ODbL: keep "© OpenStreetMap contributors".
- **Color.** The NASA Global Landslide Catalog export above, fatalities within 10 km of the point, binned as `data/AGENTS.md` says. The catalog covers 1988 to 2017, so an older or newer disaster can leave a hill `low`; its record is still in the table.
- **Preview.** Esri World Imagery export for a 10 km square, the same as the mountain previews.

<!-- hill-catalog:start -->

Written by `python ml/scripts/build_hill_catalog.py`. Each row is pinned to a Wikidata item and checked against the matching OpenStreetMap summit or cliff. The catalog column counts NASA Global Landslide Catalog events within 10 km of the point and the fatalities they record, which set the marker color. Paths are named OpenStreetMap ways and walking-route relations within 1.5 km of the point, cut to 2.5 km.

| Hill | Wikidata | OSM feature | Elevation | Named paths | Catalog within 10 km | Landslide record |
|---|---|---|---|---|---|---|
| Mam Tor (`mam-tor`) | [Q6745232](https://www.wikidata.org/wiki/Q6745232) | [node/749931231](https://www.openstreetmap.org/node/749931231) | 517 m (wikidata) | 2 | 1 events, 0 dead, `low` | Landslips on its east face give it the name Shivering Mountain; the A625 across them closed as a through road in 1979. [source](https://en.wikipedia.org/wiki/Mam_Tor) |
| White Cliffs of Dover (`white-cliffs-of-dover`) | [Q754785](https://www.wikidata.org/wiki/Q754785) | [way/114618483](https://www.openstreetmap.org/way/114618483) | 110 m (wikidata) | 6 | 0 events, 0 dead, `low` | The chalk face retreats 22–32 cm a year; large sections fell in 2001, on 15 March 2012, and in February 2020 and 2021. [source](https://en.wikipedia.org/wiki/White_Cliffs_of_Dover) |
| Beinn Luibhean (`beinn-luibhean`) | [Q41205](https://www.wikidata.org/wiki/Q41205) | [node/268767659](https://www.openstreetmap.org/node/268767659) | 858 m (wikidata) | 1 | 12 events, 0 dead, `low` | Debris flows off its slope repeatedly close the A83 at the Rest and Be Thankful; a debris-flow shelter was chosen in 2023 for the stretch below it. [source](https://www.transport.gov.scot/projects/access-to-argyll-and-bute-a83/project-details/) |
| Quiraing (`quiraing`) | [Q2385621](https://www.wikidata.org/wiki/Q2385621) | [relation/14428116](https://www.openstreetmap.org/relation/14428116) | 342 m (wikidata) | 2 | 0 events, 0 dead, `low` | Part of the Trotternish landslip that is still moving; the road across it needs repairs every year. [source](https://www.rgs.org/schools/resources-for-schools/adventure-landscapes/a-walk-around-the-quiraing) |
| St Boniface Down (`st-boniface-down`) | [Q7592680](https://www.wikidata.org/wiki/Q7592680) | [node/2293011934](https://www.openstreetmap.org/node/2293011934) | 241 m (wikidata) | 4 | 4 events, 0 dead, `low` | A major landslip in the Bonchurch Landslips below it on 10 December 2023 destroyed or closed every path there, including the Devil's Chimney. [source](https://en.wikipedia.org/wiki/Devil%27s_Chimney_(Isle_of_Wight)) |
| Mynydd Merthyr (`mynydd-merthyr`) | [Q6947865](https://www.wikidata.org/wiki/Q6947865) | none | 479 m (terrarium) | 5 | 1 events, 0 dead, `low` | A colliery spoil tip on its slope slid onto Aberfan on 21 October 1966, killing 144 people, 116 of them children. [source](https://en.wikipedia.org/wiki/Aberfan_disaster) |
| Monte Toc (`monte-toc`) | [Q2457847](https://www.wikidata.org/wiki/Q2457847) | [node/764344456](https://www.openstreetmap.org/node/764344456) | 1921 m (wikidata) | 1 | 0 events, 0 dead, `low` | Its north slope slid into the Vajont reservoir on 9 October 1963; the wave it raised killed about 2,000 people. [source](https://en.wikipedia.org/wiki/Vajont_Dam) |
| Monte San Martino (`monte-san-martino-lecco`) | [Q3861962](https://www.wikidata.org/wiki/Q3861962) | [node/457648434](https://www.openstreetmap.org/node/457648434) | 1090 m (wikidata) | 12 | 0 events, 0 dead, `low` | About 15,000 m³ of rock fell from it onto a house in Lecco on the night of 22–23 February 1969, killing seven; locals call it the monte marcio, the rotten mountain. [source](https://www.leccotoday.it/cronaca/frana-san-martino-1969.html) |
| Mount Epomeo (`mount-epomeo`) | [Q729764](https://www.wikidata.org/wiki/Q729764) | [node/26863248](https://www.openstreetmap.org/node/26863248) | 787 m (wikidata) | 2 | 1 events, 1 dead, `moderate` | A debris flow off its slope buried part of Casamicciola Terme on 26 November 2022, killing 12. [source](https://en.wikipedia.org/wiki/2022_Ischia_landslide) |
| Monte Pellegrino (`monte-pellegrino`) | [Q731916](https://www.wikidata.org/wiki/Q731916) | [node/493236385](https://www.openstreetmap.org/node/493236385) | 606 m (wikidata) | 8 | 0 events, 0 dead, `low` | Boulders from its Addaura face struck a house on 31 December 2014 and six homes were evacuated; rockfall works on that face followed. [source](http://palermo.gds.it/2014/12/31/maltempo-crollati-massi-da-monte-pellegrino-chiusa-strada-alladdaura_288263/) |
| Mont Granier (`mont-granier`) | [Q938010](https://www.wikidata.org/wiki/Q938010) | [node/11642120983](https://www.openstreetmap.org/node/11642120983) | 1933 m (wikidata) | 5 | 0 events, 0 dead, `low` | Its north face collapsed on the night of 24–25 November 1248, destroying five villages and killing more than a thousand people. [source](https://en.wikipedia.org/wiki/Mont_Granier) |
| Montserrat (`montserrat`) | [Q732115](https://www.wikidata.org/wiki/Q732115) | [way/492819272](https://www.openstreetmap.org/way/492819272) | 1236 m (wikidata) | 12 | 0 events, 0 dead, `low` | Rockfall off its conglomerate walls is monitored because it threatens the monastery, roads, and rack railway; a rockfall in April 2026 killed two climbers. [source](https://www.researchgate.net/publication/312420220) [source](https://www.theolivepress.es/spain-news/2026/04/17/second-climber-dies-after-rockfall-while-scaling-scenic-mountain-range-near-barcelona/) |
| Gnipen (`gnipen`) | [Q22352349](https://www.wikidata.org/wiki/Q22352349) | [node/1546340798](https://www.openstreetmap.org/node/1546340798) | 1567 m (wikidata) | 10 | 0 events, 0 dead, `low` | The Goldau landslide broke away below it on 2 September 1806, nearly destroying Goldau and Röthen and killing 457. [source](https://de.wikipedia.org/wiki/Gnipen) [source](https://en.wikipedia.org/wiki/Goldau_landslide) |
| Pizzo Cengalo (`pizzo-cengalo`) | [Q2574854](https://www.wikidata.org/wiki/Q2574854) | [node/26864318](https://www.openstreetmap.org/node/26864318) | 3369 m (wikidata) | 1 | 2 events, 8 dead, `moderate` | About 3 million m³ broke from its east face on 23 August 2017, killing eight hikers in Val Bondasca; the debris flow reached Bondo 6.5 km away. [source](https://nhess.copernicus.org/articles/20/505/2020/) |
| Kleines Nesthorn (`kleines-nesthorn`) | [Q22543586](https://www.wikidata.org/wiki/Q22543586) | [node/11537863918](https://www.openstreetmap.org/node/11537863918) | 3341 m (wikidata) | 3 | 0 events, 0 dead, `low` | Rockfall from its flank overloaded the Birch Glacier, which collapsed on 28 May 2025 and buried most of Blatten. [source](https://www.nature.com/articles/s43247-025-02994-8) |
| Mannen (`mannen`) | [Q11988056](https://www.wikidata.org/wiki/Q11988056) | none | 1302 m (terrarium) | 0 | 0 events, 0 dead, `low` | One of Norway's continuously monitored high-risk rock slopes; its 54,000 m³ Veslemannen block failed on 5 September 2019 after five years of radar monitoring. [source](https://ui.adsabs.harvard.edu/abs/2021Lands..18.1963K/abstract) |
| Ramnefjellet (`ramnefjellet`) | [Q11241308](https://www.wikidata.org/wiki/Q11241308) | none | 1451 m (terrarium) | 0 | 0 events, 0 dead, `low` | Rockslides from it into Lovatnet raised waves that killed 61 people on 15 January 1905 and 74 in 1936. [source](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2021.671378/full) |

<!-- hill-catalog:end -->
