# Geographic validation of the landslide models

Step 35, Sep 26, 2026. How well the terrain model and the combined terrain x rain index hold up away from the ground they were trained on. Every number here comes from `ml/artifacts/geo_validation/` and can be reproduced with the commands at the end. Data coverage and what to collect next: [`data_gap_analysis.md`](data_gap_analysis.md).

## The four numbers, kept apart

| What is measured | Design | Score | Where |
|---|---|---|---|
| Terrain, spatial CV | 10 km blocks, 5 folds, 2 km buffer | ROC-AUC 0.819, PR-AUC 0.587, lift 2.35 | `summary.csv`, scheme `spatial_cv` |
| Terrain, unseen regions | Leave one of six regions out, 2 km buffer | ROC-AUC mean 0.770 (median 0.760, min 0.589, max 0.949), PR-AUC mean 0.479, lift 2.20 | `summary.csv`, scheme `loro` |
| Terrain, Rainier (true external) | Trained on all six regions, scored once | ROC-AUC 0.597 (block bootstrap 0.52–0.67), PR-AUC 0.324, lift 1.30 | `rainier_external.csv` |
| Rain trigger alone | Case-crossover on 767 dated PNW landslides | ROC-AUC 0.755 (storm bootstrap 0.726–0.781) | `ml/artifacts/model_b_validation.json` |
| Combined index | 2 x 2 space-time design, 78 dated clusters inside the terrain region | ROC-AUC 0.861 (storm bootstrap 0.822–0.919) | `combined_validation.json` |

The terrain rows are for the deployed LightGBM (`lgbm_current`). Spatial CV overstates transfer: the same model loses 0.05 ROC-AUC on a region it has never seen and 0.22 at Rainier. The combined index is evaluated where dated events exist, not at Rainier, which has none.

## Strongest results

1. **Combined index.** It beats both inputs on dated events it was never fitted on: ROC-AUC 0.861 against 0.780 for terrain alone and 0.789 for rain alone (storm-bootstrap differences −0.113 to −0.056 and −0.137 to −0.033). A slide location outranks stable ground in the same weather cell on the same day 84% of the time. The event day outranks quiet days at the same place 90% of the time.
2. **The simpler terrain model transfers as well.** LightGBM stumps and 4-leaf trees (`lgbm_stumps`) match the deployed model on unseen regions (mean ROC-AUC 0.772 vs 0.770) and do better at Rainier (+0.022, paired block-bootstrap CI 0.009 to 0.034).
3. **Features that transfer: relief and topographic position.** Removing either costs 0.011–0.012 mean LORO ROC-AUC. Aspect is the one group flagged non-transferable in both models, but its effect is tiny.
4. **Recall targets carry over to unseen regions. Precision targets do not.** A recall-0.60 threshold picked on validation rows gives mean held-out recall 0.595. A precision-0.70 threshold gives recall 0.057.

## Audit of the pipeline before this step

1. **Data flow.** The pipeline runs in five steps:
   - `download_region.py` fetches the regional DEM and WorldCover.
   - `build_regional_features.py` computes 17 bands on a 30 m UTM grid and the USGS v3 labels:
     - Positives are WA WGS records at confidence 3 or higher, thinned to 90 m.
     - Negatives are drawn 1:3 from ground over 500 m from any record, inside the mapped footprint.
     - It writes `regional_labels.parquet` (29,404 training rows and 372 Rainier rows).
   - `train_regional_susceptibility.py` trains LightGBM on 16 features (elevation excluded) and writes the isotonic-calibrated `susceptibility.tif`.
   - `event_catalog.py`, `event_rain.py` and `event_validate.py` fit Model B's rain weights on dated events.
   - `backend/app/ml/model_b.py` combines the two in the live index.
2. **Train, validation and test.**
   - Spatial block CV uses 10 km blocks and 5 folds, dropping training rows within 2 km of a test block.
   - An inner 4-fold block CV picks hyperparameters and fits the isotonic calibrator.
   - The external test is the Rainier box, kept out of training along with a 2 km buffer.
   - Thresholds are the fixed shared bin edges.
3. **Where leakage could occur.**
   - The CV was already clean: the buffer was at least 2,021 m, and Rainier was at least 2,035 m from training.
   - The gaps were elsewhere:
     - There was no test of unseen regions.
     - Hyperparameters and features were chosen with every training region in view.
     - Rainier's numbers had already been looked at (slope alone beats the model there), so Rainier is no longer a perfectly pristine holdout. This step makes decisions on LORO only.
   - Event side: the water-year folds already dropped rows from held-out years, and no storm crosses folds.
4. **How regions were represented.**
   - The only region concepts were 10 km CV blocks and the single Rainier box.
   - Positives are uneven: the Puget lowland margin has dense lidar mapping at confidence 8, while the Cascades have sparser confidence-3 mapping.
   - Negatives are sampled at a global 1:3 ratio, so regional prevalence runs from 0.05 to 0.31.
5. **How terrain and rain combine.**
   - The live index is `sigmoid(W1*(logit(s) − logit(0.25)) + W0 + W2*r + W3*m)`.
   - Each part was fitted separately: terrain by the regional model, rain by the case-crossover logistic.
   - Adding their log-odds assumes they act independently. It had never been checked end to end, because terrain is constant within a case-crossover set.
6. **Code paths changed.** Nothing in the training or serving path. This step adds:
   - `ml/scripts/geo_metrics.py`
   - `geo_validate.py`
   - `geo_ablation.py`
   - `geo_diagnostics.py`
   - `combined_validate.py`
   - Their tests and artifacts.

   `train_regional_susceptibility.py`, `model_b.py`, and the served map are unchanged. See Recommendations.

## Method

### Regions and the holdout strategy

The training area is cut at longitude −121.9 into a lowland west (the Puget lowland margin and foothills) and a Cascades east. Each half is then cut at latitudes 46.95 and 47.225, giving six regions:

| Region | Rows | Positives | Prevalence | Positives at confidence ≥ 5 |
|---|---|---|---|---|
| south_lowland | 8,838 | 2,653 | 0.300 | 19% |
| south_cascades | 1,529 | 77 | 0.050 | 30% |
| central_lowland | 3,351 | 522 | 0.156 | 100% |
| central_cascades | 4,960 | 1,515 | 0.305 | 54% |
| north_lowland | 5,297 | 1,341 | 0.253 | 98% |
| north_cascades | 5,429 | 1,243 | 0.229 | 31% |
| Rainier (external) | 372 | 93 | 0.250 | 56% |

These are the leave-one-region-out (LORO) steps:

1. **Outer loop.** Each region is held out in turn. Training rows within 2 km of any held-out row are dropped; the smallest real gap was 2,001 m.
2. **Inner loop, on the outer training rows only.**
   - Each remaining region is held out in turn, with the same buffer.
   - Its out-of-fold scores do three jobs: they pick the family's hyperparameters by log loss, fit the Platt and isotonic calibrators, and pick every threshold.
   - `evaluate_holdout` raises if any scored row was among those validation rows.
3. **Rainier.** It is in neither loop. The final fit uses all six regions, with calibrators and thresholds from their LORO out-of-fold scores, and scores Rainier once per family.
4. **Model selection.** This rule was fixed before Rainier was scored: take the simplest family whose mean LORO PR-AUC and ROC-AUC are both within 0.01 of the best. It picked `lgbm_stumps`.

### Leakage protections, each with a test

`ml/tests/test_geo_validation.py` and `test_combined_validate.py` cover each of these:

- **Region splits.** No held-out region appears in training. Every training row is more than 2 km from every held-out row, checked against brute-force distances.
- **Inner loops.** Inner fits never see the outer region; the test counts all 96 fits of one family.
- **Thresholds and calibrators.** They are fit only on validation rows: the row count is recorded, and the set is disjoint from the held-out rows.
- **Scoring guard.** Scoring a row that fit a calibrator or threshold raises an error.
- **Combined-index fits.** They never train on a held-out water year, and no event cluster crosses folds.
- **Terrain scores for events.** They come from fits that exclude the event's region, plus 2 km around every design point of that region.

### Threshold policy

- Thresholds are chosen after ranking is measured, on validation rows only.
- Policies: max F1, target precision 0.60/0.70/0.80 (the lowest threshold that reaches the target, which keeps the most recall), and target recall 0.50/0.60/0.70 (the highest threshold that reaches it).
- A target the validation rows cannot reach is reported as unreachable and never evaluated.
- The deployed map's shared bin edge (0.45, "high") is reported alongside as the production policy.

### Calibration policy

- Raw, Platt and isotonic calibrators are all fit on the inner validation scores, compared per region, and reported with Brier score, ECE and the change in ROC-AUC.
- Probabilities are calibrated to the 1:3 design (prevalence 0.25). No region has that prevalence in reality.

### Baselines and complexity

The families, in the order the selection rule treats as simplest first:

1. Random.
2. Slope-only logistic regression.
3. L2 logistic regression (C picked by inner LORO).
4. Balanced logistic regression.
5. LightGBM stumps / 4-leaf trees.
6. The deployed LightGBM grid.
7. The deployed LightGBM with 3x positive weight.

## Results

### Before and after

"Before" is what the model card reported. "After" is what this step measures, with the same model or with the family the LORO rule selected.

| Metric | Before (deployed, reported) | After: deployed model, unseen regions | After: selected `lgbm_stumps`, unseen regions | After: `lgbm_stumps`, Rainier |
|---|---|---|---|---|
| ROC-AUC | 0.819 spatial CV; 0.597 Rainier | 0.770 (min 0.589) | 0.772 (min 0.602) | 0.619 (0.545–0.699) |
| PR-AUC | 0.575 spatial CV; 0.318 Rainier | 0.479 | 0.480 | 0.343 |
| Lift | not reported | 2.20 | 2.23 | 1.37 |
| Precision / recall at 0.45 | 0.62 / 0.40 spatial CV; 0.33 / 0.12 Rainier | 0.50 / 0.41 | 0.50 / 0.40 | 0.32 / 0.15 |
| ECE (isotonic) | 0.026 spatial CV; 0.070 Rainier | 0.082 | 0.082 | 0.056 |

No change here is claimed as a model improvement except `lgbm_stumps` over the deployed model at Rainier (+0.022 ROC-AUC, CI excludes zero). What changed is how honestly the model is measured.

### Rainier, all families (one look, after selection)

| Family | ROC-AUC | PR-AUC | Lift | Recall at validation max-F1 |
|---|---|---|---|---|
| random | 0.479 | 0.257 | 1.03 | 1.00 |
| slope_only | 0.636 | 0.352 | 1.41 | 0.94 |
| logistic | 0.677 | 0.473 | 1.89 | 0.73 |
| logistic_balanced | 0.684 | 0.481 | 1.92 | 0.72 |
| lgbm_stumps (selected) | 0.619 | 0.343 | 1.37 | 0.51 |
| lgbm_current (deployed) | 0.597 | 0.324 | 1.30 | 0.54 |
| lgbm_balanced | 0.594 | 0.325 | 1.30 | 0.52 |

Paired block-bootstrap differences for `lgbm_stumps`:

- vs slope-only: −0.018 ROC-AUC (−0.129 to 0.095). The two can't be told apart.
- vs logistic: −0.058 ROC-AUC (−0.131 to 0.017) and −0.130 PR-AUC (−0.215 to −0.032).

The LORO rule prefers boosting because it wins in the lowland regions. Rainier, a volcano, ranks linear models higher. The six regions do not represent Rainier well; see Shift.

### Unseen regions, selected family

| Region | Prevalence | ROC-AUC | PR-AUC | Lift | Precision / recall at max-F1 | TP / FP / TN / FN | ECE |
|---|---|---|---|---|---|---|---|
| south_lowland | 0.300 | 0.777 | 0.564 | 1.88 | 0.44 / 0.87 | 2307 / 2954 / 3231 / 346 | 0.036 |
| south_cascades | 0.050 | 0.602 | 0.079 | 1.57 | 0.07 / 0.51 | 39 / 561 / 891 / 38 | 0.228 |
| central_lowland | 0.156 | 0.882 | 0.499 | 3.20 | 0.44 / 0.78 | 407 / 519 / 2310 / 115 | 0.032 |
| central_cascades | 0.305 | 0.684 | 0.446 | 1.46 | 0.42 / 0.72 | 1090 / 1495 / 1950 / 425 | 0.031 |
| north_lowland | 0.253 | 0.952 | 0.861 | 3.40 | 0.78 / 0.82 | 1104 / 310 / 3646 / 237 | 0.102 |
| north_cascades | 0.229 | 0.733 | 0.431 | 1.88 | 0.36 / 0.71 | 883 / 1590 / 2596 / 360 | 0.062 |

Lowland regions score 0.78–0.95 and Cascades regions 0.60–0.73. The two best regions are the two whose positives are almost all confidence 8 (lidar-mapped deposits), so part of what LORO measures is mapping practice, not terrain.

### Ablation and transfer (`ablation_summary.csv`, `ablation_transfer.csv`)

Fixed params: the deployed LightGBM params, and logistic regression with C = 1.

| Variant (LightGBM) | Spatial CV ROC-AUC | LORO ROC-AUC mean | LORO min | LORO PR-AUC |
|---|---|---|---|---|
| slope only | 0.695 | 0.676 | 0.532 | 0.361 |
| full (16 features) | 0.819 | 0.770 | 0.589 | 0.479 |
| minus relief | 0.794 | 0.759 | 0.594 | 0.461 |
| minus position (TPI) | 0.811 | 0.759 | 0.562 | 0.471 |
| minus curvature | 0.812 | 0.767 | 0.606 | 0.468 |
| minus aspect | 0.819 | 0.771 | 0.592 | 0.479 |
| plus elevation | 0.839 | 0.791 | 0.622 | 0.521 |
| minimal transferable (slope, relief, TPI) | 0.806 | 0.763 | 0.603 | 0.454 |

- **Groups that help spatial CV but hurt unseen regions.** They are ranked by the harm:
  - LightGBM: slope pair (−0.003; redundant with relief), land cover (−0.001), aspect (−0.0005, worse in 5 of 6 regions).
  - Logistic: hydrology (−0.001), aspect (−0.0005, worse in 4 of 6).

  Every one of these is within noise. No large non-transferable feature exists among the 16.
- **Elevation.** It helps both spatial CV and LORO (+0.02), yet it lowered Rainier ROC-AUC from 0.597 to 0.576 when last tested. Every LORO region lies inside the training elevation range, so LORO cannot test the extrapolation that led to excluding elevation. It stays excluded.
- **Minimal transferable set.** Slope, relief and TPI (8 features). On unseen regions it costs 0.007 mean ROC-AUC and 0.025 PR-AUC, but raises the worst region's score. The one pre-declared Rainier look for it:
  - LightGBM: 0.631 vs 0.597 with all features.
  - Logistic: 0.732 vs 0.677.
- **Requested groups with no regional data:**
  - Geology (no map downloaded).
  - Soil (SoilGrids covers only the Rainier box).
  - Precipitation climatology (no normals downloaded).
  - Distance to roads (the OSM file is not rasterized).

  They are listed as unavailable in `report.json`, not approximated.

### Distribution shift (`shift_regions.csv`, `shift_features.csv`, `plots/shift_psi.png`)

| Held-out | Domain AUC | Validation ROC-AUC | Shift-weighted expectation | Held-out ROC-AUC | Verdict |
|---|---|---|---|---|---|
| south_lowland | 0.73 | 0.804 | 0.753 | 0.777 | no material drop |
| south_cascades | 0.81 | 0.808 | 0.704 | 0.602 | drop beyond covariate shift |
| central_lowland | 0.84 | 0.786 | 0.863 | 0.882 | no material drop |
| central_cascades | 0.80 | 0.815 | 0.695 | 0.684 | drop explained by covariate shift |
| north_lowland | 0.95 | 0.757 | 0.868 | 0.952 | no material drop |
| north_cascades | 0.76 | 0.803 | 0.716 | 0.733 | drop explained by covariate shift |
| Rainier | 0.86 | 0.801 | 0.691 | 0.619 | drop beyond covariate shift |

How the columns are built:

- **Shift-weighted expectation.** The inner validation scores are reweighted by the domain classifier's density ratio. This estimates the held-out ROC-AUC if only the features had moved.
- **Verdict.** A real score more than 0.03 below that expectation means feature shift does not explain the drop.

What the shift at Rainier looks like:

- **Relief is far outside the training distribution.** `relief_1000` has SMD 1.48 and PSI 3.7; `relief_500` has PSI 2.7. Elevation has PSI 4.8, but it isn't a model input.
- **The labels differ.** 20% of Rainier's positives come from inventories other than WA WGS: USGS seismogenic, slow-moving and seed points.

South Cascades and Rainier lose 0.07–0.10 beyond what feature shift explains. Label differences, landslide types (debris flows on volcanic terrain), or a missing process are all consistent with that.

### Errors (`errors_by_band.csv`, `errors_feature_contrast.csv`, `top_false_*.csv`)

**Unseen regions** (thresholds at each fit's validation max-F1):

- **False positives** are steep (mean slope 21.6° vs 10.9° for true negatives), rough, high-relief and concave, and sit in valley bottoms (mean TPI −16 m).
- **False negatives** are gentle and low-lying (mean slope 17° vs 23° for true positives). Among the 50 most confident misses the mean slope is 3.9°, and 35 of the 50 are in south_lowland: deposits mapped on flats.
- **By elevation**, precision falls from 0.67 below 300 m to 0.08 above 1,500 m.

**Rainier:**

- **False negatives** are the highest-relief slides (mean `relief_1000` 856 m vs 624 m for true positives), which is where the model extrapolates.
- **False positives** sit near drainages (156 m vs 282 m for true negatives) with negative TPI: valley floors and debris-flow channels that carry no inventory point.

**Export.** Coordinates of the 50 highest-confidence false positives and false negatives, for unseen regions and for Rainier, are in `top_false_positives.csv` and `top_false_negatives.csv`. The 5 km cells with the most errors are in `errors_spatial_clusters.csv`.

### Thresholds (`thresholds.csv`, selected family)

| Policy (picked on validation) | Validation precision / recall | Unseen regions: mean precision / recall (min) | Rainier precision / recall |
|---|---|---|---|
| max F1 | 0.45 / 0.75 | 0.42 / 0.74 (precision 0.07, recall 0.51) | 0.33 / 0.51 |
| precision 0.60 | 0.60 / 0.29 | 0.53 / 0.29 (0.09, 0.17) | 0.41 / 0.10 |
| precision 0.70 | 0.72 / 0.04 | 0.75 / 0.06 | nothing flagged |
| precision 0.80 | 0.85 / 0.001 | 4 rows flagged in 29,404 (all in north_lowland) | nothing flagged |
| recall 0.50 | 0.53 / 0.50 | 0.47 / 0.50 (0.06, 0.22) | 0.39 / 0.26 |
| recall 0.60 | 0.50 / 0.60 | 0.45 / 0.60 (0.06, 0.33) | 0.42 / 0.42 |
| recall 0.70 | 0.47 / 0.70 | 0.43 / 0.69 (0.06, 0.45) | 0.35 / 0.46 |

**Recommendation.**

- Set operating points by recall. Recall 0.60 holds on average across unseen regions and reaches 0.42 at Rainier, where precision stays near 0.42.
- Precision targets of 0.70 and above are not achievable: the model's top scores are not pure enough anywhere.
- Every precision here is at the design prevalence of 0.25. At a real prevalence \(\pi\), precision is `recall·π / (recall·π + FPR·(1−π))` (`geo_metrics.precision_at_prevalence`). Precision falls in proportion to prevalence when positives are rare.

### Calibration (`calibration.csv`, `reliability.csv`, `plots/reliability.png`)

| Scheme | Raw ECE | Platt ECE | Isotonic ECE | ROC-AUC change from calibration |
|---|---|---|---|---|
| Spatial CV | 0.023 | 0.026 | 0.030 | ≤ 0.001 |
| Unseen regions (mean) | 0.080 | 0.081 | 0.082 | ≤ 0.001 |
| Rainier | 0.062 | 0.054 | 0.056 | +0.001 (isotonic ties) |

- Calibrators fit on validation rows don't fix regional calibration. Region-level ECE follows prevalence: south_cascades, at prevalence 0.05, has ECE 0.21–0.23 under every method.
- Calibration doesn't change ranking.
- **Recommendation.** Keep isotonic, or Platt, which is simpler and equal here, for the 1:3 design scale. Keep presenting the map as a relative index, as the card already does.

### Combined index (`combined_validation.json`, `combined_metrics.csv`)

**Design.** It covers 78 clusters with the full 2 x 2 design (82 with a record in the terrain region), 36 storms and 11 water years, for 1,950 rows at design prevalence 0.04. Case points are actual record locations, preferring precise USGS records. Five random draws of which record is the case moved terrain ROC-AUC by less than 0.02 (`combined_case_draws.csv`).

| Score | ROC-AUC (storm CI) | PR-AUC | Lift | Beats same place, other day | Beats other place, same day | Beats other place, other day |
|---|---|---|---|---|---|---|
| terrain only | 0.780 (0.735–0.843) | 0.113 | 2.83 | 0.500 | 0.841 | 0.841 |
| rain only (live weights) | 0.789 (0.740–0.833) | 0.122 | 3.05 | 0.904 | 0.500 | 0.904 |
| live index | 0.861 (0.822–0.919) | 0.229 | 5.73 | 0.904 | 0.841 | 0.937 |
| live index, past rain only | 0.854 (0.816–0.903) | 0.231 | 5.77 | 0.867 | 0.841 | 0.934 |
| fitted additive, out-of-fold | 0.826 (0.790–0.914) | 0.159 | 3.97 | 0.897 | 0.841 | 0.949 |
| fitted with interaction, out-of-fold | 0.826 | 0.159 | 3.96 | 0.897 | 0.841 | 0.950 |

**Is the combination justified?**

- It is a heuristic product of two separately fitted parts. On this design it beats both parts.
- Refitting doesn't beat it (difference −0.046 to +0.002), and an interaction term adds nothing, so these data don't contradict the independence assumption.
- The full-data terrain coefficient is 0.68 against the live W1 = 1.0: terrain may be slightly overweighted. With 36 storms the out-of-fold fit can't show it.
- Removing the reanalysis "perfect forecast" costs 0.007.

**Precise locations.** The 21 clusters with precise locations give 0.893 for the live index. The GLC-only clusters (location error up to 5 km) dilute terrain.

**Rainier.** None of this is Rainier validation: no dated cluster falls in the Rainier box.

## Recommendations

1. **Swap the deployed terrain family for `lgbm_stumps`.** It is simpler, equal on unseen regions, and better at Rainier with a CI that excludes zero. It would change the served map and the backend tests that pin map values, so it is left for a separate step.
2. **Don't switch to logistic regression or the minimal feature set on the strength of Rainier.** Both look better there, but Rainier is the only test that could confirm it, and it has now been looked at. Confirm with new Cascades or volcano labels first (see the data gap doc).
3. **Use recall-target operating points and drop precision targets of 0.70 and above.** Keep calling the output a relative index, not a probability.
4. **Keep elevation excluded.**
5. **Terrain weight in the combined index.** Revisit W1 once more dated storms with located slides exist.

## Limitations

- **Rainier is small and no longer pristine.** It has 93 positives, so its intervals are about ±0.075 ROC-AUC, and its numbers were seen before this step. It was not used for any decision here.
- **Regions differ in more than terrain.** The six regions differ in mapping practice as well as terrain, so LORO measures both.
- **Prevalence is a design choice.** It is set by 1:3 sampling across the whole footprint, so regional prevalence (0.05–0.31) is an artifact of where mapping happened. Compare lift, not raw PR-AUC.
- **Hyperparameters in two analyses saw every training region.** The ablation reuses the deployed params, and the combined check trains terrain with the deployed family; those params came from CV over all training regions. The main LORO comparison re-selects them inside each fold.
- **The combined check is small and specific.** It uses 36 storms, lowland-heavy regions, lead-0 reanalysis rain, and design prevalence. Its probabilities and the 0.45 bin are not real-world rates.

## Reproduce

From the repo root, with the ML venv (`ml/.venv`) and the processed tables in place:

```bash
python ml/scripts/build_regional_features.py        # regional_labels.parquet (if missing)
python ml/scripts/geo_validate.py                   # LORO, spatial CV, Rainier, ablation, shift, errors, plots (~6 min)
python ml/scripts/combined_validate.py              # combined index on dated events (~2.5 min; --rebuild-points to resample)
python -m pytest ml/tests/test_geo_validation.py ml/tests/test_combined_validate.py -q
```

Outputs are deterministic: seed 26 for the terrain work, 20260926 for the event work. The tests rerun a pipeline twice and compare the CSVs byte for byte.
