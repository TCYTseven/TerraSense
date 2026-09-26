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
| `data/seed/landslides.geojson` | NASA Global Landslide Catalog local export, supplemented by Washington State Landslide Inventory Database — Landslide Compilation | 2026-09-26 | Done. 37 mapped events total: 4 NASA events (1 at 1km accuracy, 3 at 5km) plus 33 supplemental 1km inventory points |
| `data/seed/trails.geojson`, `data/seed/trail_segments.geojson` | OpenStreetMap via Overture Maps | 2026-09-25 | Done. Written by `ml/scripts/import_trails.py` |
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
- **Primary source:** NASA Global Landslide Catalog, "Global Landslide Catalog Export", data.nasa.gov dataset `dd9e-wu2v`. Local refresh command: `python ml/scripts/download_sources.py --only landslides --glc-csv /Users/Aarav/Documents/Global_Landslide_Catalog_Export_rows.csv --force`.
- **Supplemental source:** Washington Geological Survey, Washington State Landslide Inventory Database, **Landslide Compilation** layer 131. URL: https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/131
- **Query URL:** https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/131/query
- **Licence/attribution:** Washington Geological Survey; retain the source URL and inventory name with the derived seed. The layer warns that mapped coverage and confidence vary by source and scale; its representative points are conservatively labeled `location_accuracy: 1km` for training.
- **Output:** a FeatureCollection of 37 Points inside the box, oldest first. NASA points preserve their catalog accuracy (`1km` or `5km`); polygon features are clipped to the bbox and converted to interior representative points with conservative `1km` accuracy. Step 11 uses only `exact` and `1km` points, yielding 34 usable training points. Properties: `id`, `date` (ISO or null), `title`, `category`, `trigger`, `size`, `setting`, `location_accuracy`, `fatalities`, `source_name`, `source_link`, `catalog`, `inventory_confidence`, `source_layer`.

**To refresh.** On a network that reaches data.nasa.gov, run `python ml/scripts/download_sources.py --only landslides`. If NASA is unavailable, the script automatically queries the Washington fallback. To use a downloaded NASA CSV explicitly, run `python ml/scripts/download_sources.py --only landslides --glc-csv path/to/export.csv`; sparse high-accuracy NASA results are supplemented with the Washington inventory.

**For step 11.** The catalog geocodes events from news reports, so `location_accuracy` runs from `exact` to `50km`, and the box may hold only a few events. Keep `exact` and `1km` points for pixel labels. A USGS inventory, such as the U.S. Landslide Inventory, can add points from a network that reaches ScienceBase.

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
