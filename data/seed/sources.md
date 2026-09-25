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
| `data/seed/landslides.geojson` | NASA Global Landslide Catalog | Pending | Blocked. See below |

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

## Landslide points: `data/seed/landslides.geojson` (pending)

- **Status:** not created. On 2026-09-25 the build container's network policy refused `data.nasa.gov` (HTTP 403), along with the USGS and Washington DNR hosts that serve landslide inventories (`www.usgs.gov`, `www.sciencebase.gov`, `gis.dnr.wa.gov`). No point was placed by hand.
- **Source:** NASA Global Landslide Catalog, "Global Landslide Catalog Export", data.nasa.gov dataset `dd9e-wu2v`.
- **URL (script default):** https://data.nasa.gov/api/views/dd9e-wu2v/rows.csv?accessType=DOWNLOAD, cached as `data/raw/nasa_glc_export.csv`.
- **Dataset page:** https://data.nasa.gov/Earth-Science/Global-Landslide-Catalog-Export/dd9e-wu2v
- **Licence:** NASA open data. Confirm the licence on the dataset page when you download. Cite Kirschbaum et al. (2010), A global landslide catalog for hazard applications, *Natural Hazards* 52, 561 to 575, doi:10.1007/s11069-009-9401-4.
- **Output:** a FeatureCollection of Points inside the box, oldest first. Properties: `id`, `date` (ISO), `title`, `category`, `trigger`, `size`, `setting`, `location_accuracy`, `fatalities`, `source_name`, `source_link`, `catalog`.

**To finish.** On a network that reaches data.nasa.gov, run `python ml/scripts/download_sources.py --only landslides`. Or download the CSV in a browser and run `python ml/scripts/download_sources.py --only landslides --glc-csv path/to/export.csv`. If the API URL has moved, download the CSV from the dataset page and pass it the same way. Then fill in the access date and the point count above.

**For step 11.** The catalog geocodes events from news reports, so `location_accuracy` runs from `exact` to `50km`, and the box may hold only a few events. Keep `exact` and `1km` points for pixel labels. A USGS inventory, such as the U.S. Landslide Inventory, can add points from a network that reaches ScienceBase.
