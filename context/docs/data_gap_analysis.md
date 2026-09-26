# Data gap analysis

Step 35, Sep 26, 2026. What labeled data the landslide models have, where it is thin, and what would change the conclusions in [`geographic_validation.md`](geographic_validation.md). Every count below comes from `data/processed/regional_labels.parquet`, the USGS v3 inventory read by `build_regional_features.read_inventory()`, and `data/processed/events/`. No label has been invented or inferred.

## Terrain labels (susceptibility model)

Positives are WA WGS records at confidence 3 or higher, thinned to one per 90 m. Negatives are cells over 500 m from any record inside the mapped footprint, drawn 1:3 across the whole region. Regions are those of `geo_validate.py`.

| Region | Positives | Negatives | Prevalence | Positives at confidence 8 | Inventory records, any confidence (WA WGS / other) |
|---|---|---|---|---|---|
| south_lowland | 2,653 | 6,185 | 0.300 | 19% | 3,236 / 37 |
| south_cascades | 77 | 1,452 | 0.050 | 30% | 378 / 20 |
| central_lowland | 522 | 2,829 | 0.156 | 100% | 629 / 9 |
| central_cascades | 1,515 | 3,445 | 0.305 | 54% | 1,779 / 5 |
| north_lowland | 1,341 | 3,956 | 0.253 | 98% | 2,164 / 64 |
| north_cascades | 1,243 | 4,186 | 0.229 | 31% | 1,466 / 11 |
| Rainier box (external) | 93 | 279 | 0.250 | 56% | 74 / 32 |

**What the table shows.**

- **Two mapping practices.** The central and north lowland positives are almost all confidence 8, lidar-mapped deposits with drawn extents. The Cascades and the south lowland are mostly confidence 3, points "at or near" a slide.
  - The two confidence-8 regions are the two where the model scores highest on unseen ground (ROC-AUC 0.88 and 0.95).
  - Part of the regional spread measures mapping practice, not terrain.
- **Prevalence is a sampling artifact.** It runs from 0.05 to 0.31 because negatives are sampled over the whole footprint. It says where mapping happened, not how common slides are. Compare regions by lift (PR-AUC / prevalence).
- **South Cascades, the region next to Rainier, is the thinnest.** It has 77 positives, and its unseen-region ROC-AUC (0.60) has the widest uncertainty of the six.
- **Rainier's positives are mixed.**
  - 74 are WA WGS.
  - 7 are USGS seismogenic mass movements.
  - 10 are seed points from the Washington compilation.
  - 1 is from the GLC and 1 is a slow-moving slide.

  Their mix of landslide types (volcanic debris flows, rockfall, deep-seated slumps) differs from the lowland training positives. The shift analysis finds a drop at Rainier that feature shift does not explain (held-out 0.62 against a shift-weighted expectation of 0.69).
- **Terrain extrapolation.** Rainier's relief is outside most of the training range (`relief_1000` PSI 3.7; 7% of Rainier rows fall outside the training 1st–99th percentile range). Elevation was excluded for this reason.

### Features requested but missing for the region

| Feature | Status | What would supply it |
|---|---|---|
| Geology / lithology | Not downloaded | WA DNR 1:100,000 surface geology (volcanic, glacial, sedimentary units) |
| Soil | SoilGrids covers only the Rainier box (`data/raw/soilgrids/`) | SoilGrids 250 m over `REGION_BBOX`, or SSURGO |
| Precipitation climatology | Not downloaded | PRISM 30-year normals (800 m) |
| Distance to roads | `data/raw/osm/washington-latest.osm.pbf` exists but is not rasterized | Rasterize OSM roads to the 30 m grid; road cuts are a known trigger and a known mapping bias |

Each would enter the ablation (`geo_ablation.FEATURE_GROUPS`) and be kept only if it helps on unseen regions, not just in spatial CV.

## Dated events (rain trigger and combined index)

The event catalog (`event_catalog.py`) holds 908 dated clusters from 488 storms, water years 1980–2023, over western Washington and northwest Oregon (542 in Washington, 366 in Oregon). Inside the terrain model's region:

| Region | Dated records | Clusters | Storms | Water years | Span |
|---|---|---|---|---|---|
| south_lowland | 1,034 | 20 | 3 | 3 | 2009–2017 |
| south_cascades | 26 | 6 | 4 | 3 | 2009–2014 |
| central_lowland | 7 | 7 | 7 | 4 | 2011–2017 |
| central_cascades | 0 | 0 | 0 | 0 | none |
| north_lowland | 51 | 46 | 30 | 11 | 1986–2017 |
| north_cascades | 11 | 3 | 2 | 2 | 2009–2014 |
| Rainier box | **0** | **0** | **0** | **0** | none |

**What the table shows.**

- **Rainier has no dated event records.** The combined index has never been checked there, and nothing in the repo claims it has.
- **Heavily clustered in time.** South lowland's 1,034 dated records come from 3 storms: reconnaissance mapping after the January 2009 and other large storms. Storms, not records, are the independent unit; the combined check has 36.
- **Imprecise locations.** 58 of the 82 in-region clusters are from NASA's GLC alone, with locations good to 1–5 km. Terrain at such a point is noise. The 21 clusters with precise USGS locations give a higher combined ROC-AUC (0.893 vs 0.861 for all).
- **Mostly lowland.** Only 9 of the 82 clusters are in a Cascades region.

## Sample sizes that would help

The ROC-AUC interval widths come from the Hanley–McNeil variance. They are scaled by the design effect measured at Rainier, where the 2 km block bootstrap is 11% wider than the formula.

| Goal | Needed |
|---|---|
| Rainier (or any new area) terrain ROC-AUC to ±0.05 | about 200 positives and 600 negatives |
| The same to ±0.03 | about 550–600 positives and 1,650–1,800 negatives |
| Tell LightGBM stumps from logistic at Rainier with 80% power (current gap 0.06, CI −0.13 to 0.02) | about 3–4x the current 93 positives |
| Combined index ROC-AUC to ±0.05 in a new area | 30–40 storms with located slides (the in-region check has 36 storms and gets ±0.05) |
| Fit the terrain weight W1 out-of-fold rather than in-sample | about 100 storms with precise locations in varied terrain |

## Data requirements for a real Rainier validation of the combined index

A Rainier check needs dated landslides inside `[-121.93, 46.76, -121.54, 46.96]`, not borrowed from the lowlands.

1. **Events.** At least 30 rain-triggered landslides or debris flows with a date good to one day and a location good to about 100 m, spread over at least 15 storms. Candidate sources, none downloaded yet:
   - Mount Rainier National Park and USGS dated debris-flow histories for Tahoma, Kautz, Nisqually and South Puyallup creeks (not yet checked for location precision).
   - USGS Cascades Volcano Observatory lahar and debris-flow reports.
   - WSDOT and park road-closure logs for SR 410, SR 706 and Stevens Canyon Road (dated, located, but biased toward roads).
   - NASA GLC and COOLR entries in the box (there are none at one-day precision today).
2. **Negatives.** For each event, same-place control days, as `event_rain.py` already builds. Also stable cells in the same weather cell, which needs a mapped footprint in the park: lidar-based mapping from WA DNR. The Rainier box holds 106 inventory records of any confidence, against 400 to 3,300 in each training region.
3. **Weather.** ERA5 via the Open-Meteo archive works as it does for the other events. Snow and rain-on-snow matter more at Rainier: the `rich_features` already carry them.
4. **Kept separate.** Park debris flows are often glacial-outburst or rain-on-snow driven, not rainfall-threshold driven. Tag the trigger, and keep non-rain events out of the rain-trigger check.
5. **Evaluation.** Run `combined_validate.py` unchanged on the new events: region `rainier`, terrain from the model trained without the box and its 2 km buffer. Report the result once.

Until those exist, the app's card should keep saying the combined index is validated on regional dated events, not at Rainier.

## The biggest single bottleneck

**Labels that match Rainier's terrain and mapping practice.** Almost everything the model learns comes from lowland lidar mapping. The regions it transfers to best are those with the same mapping practice, and at Rainier it drops by more than feature shift explains. About 200 or more located positives from the volcano and the south Cascades, mapped with one consistent method, would do more for external validity than any model or feature change tested here.
