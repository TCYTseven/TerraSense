# TerraSense — Landslide, Rockfall & Snow-Avalanche Runout Modeling Reference (`docs/runout-models.md`)

For a browser-speed runout ("path") simulator on a DEM, the model to build is a Flow-Py/Flow-R/GPP-style multiple-flow-direction router: Holmgren exponent weighting, a persistence (inertia) term, and an energy-line (reach-angle / Fahrböschung) stopping rule. Next to it, add an optional 1-D Voellmy or Perla–Cheng–McClung (PCM) velocity profile along the most likely path. Use depth-averaged solvers (RAMMS, AvaFrame com1DFA, r.avaflow, D-Claw, Titan2D) only offline, for validation and calibration.

**TerraSense today.** **Simulate** on the mountain page plays an **illustrative rain-triggered landslide / debris-flow** runout (`backend/app/ml/runout.py`), not a snow-avalanche forecast. Mount Rainier and other alpine mountains still sit in **avalanche terrain**; agents discuss weather and snow in traces, and rangers expect avalanche-bulletin language in disclaimers. The **snow-avalanche** material below is pertinent for mountains, for calibrating future runout modes, and for not conflating debris-flow playback with ski-tour or winter hazard maps.

## TL;DR

- **Tier A (real-time extent):** Flow-Py's published algorithm is the best-documented open template for TerraSense. It takes only a DEM, release cells and at least four parameters. Route "flux" to the 8 neighbours with weights $(\tan\phi_i)^{x}$, multiply by a persistence term, and stop wherever $Z^{\delta}=Z^{\gamma}-Z^{\alpha}<0$ or the flux falls below a cutoff. Suggested exponents are about **8 for avalanches**, 4–6 for debris flows and 75 (near single-flow) for rockfall.
- **Tier B (speed/intensity):** along the dominant path, integrate a lumped-mass Voellmy sled, $dv/dt=g(\sin\psi-\mu\cos\psi)-g v^2/(\xi h)$, or the closed-form PCM segment update. Parameter defaults: snow $\mu\approx0.155$–$0.16$, $\xi\approx1100$–$1400\ \mathrm{m\,s^{-2}}$ for extreme avalanches (Buser & Frutiger 1980). Rock avalanches back-analysed with DAN: $f\approx0.03$–$0.24$, $\xi\approx100$–$1000\ \mathrm{m\,s^{-2}}$ (Hungr & Evans 1996, as summarised by McKinnon et al. 2008). Debris flows in Flow-R: $V_{max}\approx15\ \mathrm{m\,s^{-1}}$ with a minimum travel angle of 11° (coarse) or 7° (fine) (Horton et al. 2013).
- **Tier C (validation only):** RAMMS, AvaFrame com1DFA, r.avaflow, D-Claw and Titan2D solve the depth-averaged mass/momentum equations. They need release thickness or volume, calibrated rheology and CFL-limited time stepping, so they are not suited to real-time use in a web app. Every output shown to hikers and rangers must be labelled as illustrative susceptibility, not an official hazard assessment.

---

## 1. Purpose and how to use this file

This document is context for an AI coding assistant (and humans) improving the TerraSense simulation column and mountain hazard copy: which models exist for where a mass movement goes and how far, their equations with every variable defined, sourced parameter defaults, raster-DEM implementation, **snow-avalanche runout for alpine mountains**, and safety language.

Conventions: $z$ is elevation (m), $s$ is horizontal (projected) distance along the path (m), $g=9.81\ \mathrm{m\,s^{-2}}$, $\psi$ or $\beta$ is the local slope angle, and angles are in degrees unless stated. "Verified" means checked against the primary paper, official model documentation, or the publisher record. Items marked ⚠ are second-hand or standard textbook forms; check them before relying on them.

---

## 2. Model-selection summary

| Family | Representative models | Processes | Inputs | Output | Cost | Fit for TerraSense |
|---|---|---|---|---|---|---|
| Empirical geometric (energy line / reach angle) | Heim 1932; Scheidegger 1973; Corominas 1996; α–β (Lied & Bakkehøi 1980; Bakkehøi et al. 1983) | Rock avalanche, landslides, **snow avalanche** | Profile or DEM, sometimes volume | Max runout point / angle | Trivial | ✅ Stopping rule for Tier A |
| DEM flow routing + energy line | Flow-R (Horton et al. 2013), Flow-Py / com4FlowPy (D'Amboise et al. 2022) | All GMFs (by parameter choice) | DEM, release cells, 2–6 params | Extent, relative susceptibility, energy-line "velocity" | Seconds–minutes per region | ✅ **Tier A core** |
| Lumped-mass sled | Voellmy 1955; Voellmy–Salm; PCM (Perla et al. 1980) | **Snow avalanche**, debris flow, rock avalanche | Path profile, μ, ξ or M/D | v(s), stop point | Trivial | ✅ **Tier B** |
| Depth-averaged continuum | RAMMS (Christen et al. 2010); AvaFrame com1DFA (Tonnel et al. 2023) | All flow-like | DEM, release thickness/volume, rheology | h(x,y,t), u(x,y,t) | Minutes–hours, CFL-limited | 🔶 Tier C validation (e.g. RAMMS for **snow** on Rainier-scale terrain) |
| Initiation / source | AutoATES PRA (Toft et al. 2024) | **Avalanche release**, ATES exposure | DEM, forest density | Start cells, terrain class | Moderate | ✅ **Mountain context** (not Simulate today) |

---

## 3. Empirical and geometric runout

### 3.1 Energy line / angle of reach (Fahrböschung)

**Sources.** Heim (1932); Scheidegger (1973); Corominas (1996).

**Core relation.** The runout angle $\alpha$ is the angle of the line joining the top of the source to the distal toe of the deposit:
$$\tan\alpha = \frac{H}{L} = \frac{z(s_0)-z(s_\alpha)}{s_\alpha-s_0}$$
- $H$: fall height (m); $L$: horizontal travel distance (m)
- $s_0$: release position; $s_\alpha$: stopping position

$H/L$ is also read as an apparent friction coefficient. In the energy-line picture, the vertical gap between energy line and terrain, $Z^{\delta}$, is kinetic-energy head, so $v\approx\sqrt{2gZ^{\delta}}$.

**Volume–mobility regression (Scheidegger 1973, verified):**
$$\log_{10} f = -0.15666\,\log_{10}V + 0.62419,\qquad r = 0.82$$
with $f=H/L$ and $V$ in m³.

**Corominas (1996), verified.** Across 204 landslides of all sizes, the reach angle decreases steadily with volume whatever the mechanism.\[4\]

**Implementation notes.** α alone cannot tell you the path; pair it with a router (Section 4). For conservative display, use a smaller α. TerraSense's live debris-flow playback uses a fixed 11° travel angle from Flow-R (Section 4.3), not α–β.

### 3.2 Snow avalanche α–β model

**Sources.** Lied & Bakkehøi (1980), J. Glaciol. 26(94):165–177 (111 Norwegian paths; four-variable regression on $y''$, β, H, θ; R = 0.95, SD = 2.3°).\[6\] Bakkehøi, Domaas & Lied (1983), Ann. Glaciol. 4:24–29 (206 avalanches) give the one-variable form (verified):\[7\]
$$\alpha = 0.96\,\beta - 1.4^\circ,\qquad SD = 2.3^\circ,\ R = 0.92$$
- $\beta$: angle from release to the "β-point", where the profile slope first drops below 10°\[8\]\[9\]
- $\alpha$: predicted angle from release to the extreme (~100-year) runout point

**General form (AvaFrame com2AB, verified):**
$$\alpha_j = k_1\beta + k_2 z'' + k_3 H_0 + k_4 + j\,SD$$\[8\]
with $H_0$ the elevation loss and $z''$ the curvature of a quadratic profile fit, and $j \in \{-2,-1,0,1\}$.\[10\] AvaFrame notes $\alpha_{-1}=\alpha-SD$ gives a longer runout, and the probability of the runout being shorter than $s_{\alpha_{-1}}$ is about 83%. com2AB is calibrated for the Austrian Alps, resamples paths at ≤10 m, and requires `dsMin = 30 m` below 10° after the β-point.\[8\]\[11\]

Gauer, Kronholm, Lied, Kristensen & Bakkehøi (2010, Cold Reg. Sci. Technol. 62(1):42–54, doi:10.1016/j.coldregions.2010.02.001) used the dataset of around 320 "extreme"-avalanche runout observations that originally formed the basis of the α–β model. They found the mean retarding acceleration rises roughly linearly with $g\sin\beta$ — the physical reason α–β works.

**Runout ratio (McClung & Lied 1987, CRST 13(2):107–119; DOI reconstructed ⚠).** Fits $\Delta x/X_\beta$ (distance past the β-point over horizontal distance from release to β-point) to a Gumbel extreme-value distribution, then applies engineering confidence limits.\[12\]\[13\]

**TerraSense use (mountains).** On the most-likely Tier A path for a **future snow mode**, find β by walking downslope until the slope first drops below 10°, apply $\alpha = 0.96\beta - 1.4^\circ$ (optionally $\alpha - SD$), and use it as the snow stopping angle. Example: β = 30° gives α ≈ 27.4° (conservative ≈ 25.1°). Until then, cite α–β when explaining why Simulate is **not** replacing avalanche bulletins or ATES maps on Rainier.

---

## 4. DEM flow routing adapted to mass movements (Tier A core)

### 4.1 Classic hydrologic routers

| Algorithm | Citation | Rule | Behaviour for mass flows |
|---|---|---|---|
| D8 | O'Callaghan & Mark (1984) | All flow to steepest of 8 neighbours | Too straight and narrow; quick runout-length checks only (Horton et al. 2013) |\[14\]
| Holmgren | Holmgren (1994) | $f_i\propto(\tan\beta_i)^x$ | Tunable divergence; recommended |

**Holmgren weighting (as implemented in Flow-R, verified):**
$$p_i^{fd}=\frac{(\tan\beta_i)^x}{\sum_{j=1}^{8}(\tan\beta_j)^x},\qquad \tan\beta_i>0,\ x\in[1,\infty)$$
$x=1$ behaves like MFD; $x\to\infty$ becomes single flow direction. Claessens et al. (2005) suggested $x=4$ for debris flows; Horton et al. call 4–6 "a commonly chosen range".\[14\] **Modified Holmgren (Flow-R):** raise the central cell by $dh$ (e.g., 2 m) before computing gradients to smooth DEM roughness.

### 4.2 Persistence (inertia) functions

Flow-R (Horton et al. 2013, after Gamma 2000) weights each direction by its turn angle from the previous flow direction, $p_i^{p}=w_{\alpha(i)}$:\[14\]

| Weighting | $w_0$ | $w_{45}$ | $w_{90}$ | $w_{135}$ | $w_{180}$ |
|---|---|---|---|---|---|
| Proportional | 1 | 0.8 | 0.4 | 0 | 0 |
| Cosines | 1 | 0.707 | 0 | 0 | 0 |
| Gamma (2000) | 1.5 | 1 | 1 | 1 | 0 |

Combined and renormalised so susceptibility is conserved:
$$p_i=\frac{p_i^{fd}\,p_i^{p}}{\sum_{j}p_j^{fd}\,p_j^{p}}\;p_0$$

### 4.3 Flow-R (Horton, Jaboyedoff, Rudaz & Zimmermann 2013)

- **Citation:** NHESS 13:869–885, doi:10.5194/nhess-13-869-2013 (CC BY 3.0 article). https://www.flow-r.org \[14\]\[17\]
- **Scope:** regional debris-flow susceptibility; also relevant for rockfall, **snow avalanches** and floods. Volume and mass are *not* modelled.\[14\]

**Energy balance per cell step (unit mass):**
$$E^{i}_{kin}=E^{0}_{kin}+\Delta E^{i}_{pot}-E^{i}_{f}$$

**Simplified friction-limited model (SFLM):** $E^{i}_f=g\,\Delta x\tan\varphi$, with velocity cap
$$V_i=\min\left\{\sqrt{V_0^2+2g\Delta h-2g\Delta x\tan\varphi},\;V_{max}\right\}$$
Minimum travel angle in the Swiss Alps: about **11°** for coarse/medium debris flows, **7°** for fine-grained. Observed maximum Swiss debris-flow velocities were 13–14 m s⁻¹, so the authors often use $V_{max}=15\ \mathrm{m\,s^{-1}}$.\[14\] (TerraSense's implemented router uses the 11° angle and Holmgren spread on a local DEM; it does not yet use $V_{max}$ or persistence.)

**PCM option:** the closed-form segment update (Section 5.2), with momentum correction $V_i'=V_i\cos(\beta_i-\beta_{i+1})$ at sharp slope decreases.\[14\]

### 4.4 Flow-Py v1.0 / AvaFrame com4FlowPy (D'Amboise et al. 2022)

- **Citation:** GMD 15:2423–2439, doi:10.5194/gmd-15-2423-2022 (CC BY 4.0 article).\[18\] Code: Zenodo doi:10.5281/zenodo.5027274; now maintained as `com4FlowPy` in AvaFrame.\[18\]\[19\]

**Geometry along a path (verified from AvaFrame theory docs):**
$$Z^{\alpha}=\tan\alpha\,(s-s_0),\quad Z^{\gamma}=z(s_0)-z(s),\quad Z^{\delta}=Z^{\gamma}-Z^{\alpha}$$
A neighbour can receive flow only if the resulting $Z^\delta>0$.

**Terrain term (Holmgren):**
$$T_i=\frac{(\tan\Phi_i)^{exp}}{\sum_{n=1}^{8}(\tan\Phi_n)^{exp}},\qquad \Phi_i=\frac{\psi_i+\pi/2}{2}$$
The remapping $\Phi$ lets flow continue across flat or uphill cells. Docs: "**For avalanches an exponent of 8 shows good results.** To reach a single flow in steep terrain (rockfall, soil slides, steepest descent), an exponent of 75 is considered."\[20\]

**Stopping:** $Z^\delta<0$ **or** $R_i<R_{stop}$.\[20\]

### 4.6 AutoATES v2.0 (Toft et al. 2024) — recreational avalanche exposure

- **Citation:** NHESS 24:1779–1793, doi:10.5194/nhess-24-1779-2024 (CC BY 4.0).\[28\]
- **Pipeline:** fuzzy-logic potential release areas (after Veitinger et al. 2016 and Sharp 2018, with forest density) → **Flow-Py runout** → ATES classes 0–4.\[28\]\[29\]
- **Inputs:** DEM plus forest density (canopy cover, stem density or basal area). DEM-only runs are valid only for open terrain.\[28\]\[30\]
- **Validation (F1 vs expert consensus, western Canada):** Bow Summit 64% → 77%; Connaught Creek 40% → 71%.\[31\]
- **Stated main limitation:** "determination of optimal input parameters for different regions and climates."\[28\]
- **Why it fits TerraSense mountains.** Toft et al. (2024), citing Techel et al. (2016, 2018) and Birkeland et al. (2017), report that snow avalanches lead to a yearly average of 140 fatal accidents in Europe and North America, and that more than 90% of fatal avalanche accidents are related to recreational activity and triggered by the victim or someone in their party (Schweizer & Lütschg 2001; Techel & Zweifel 2013; Engeset et al. 2018) — the same audience as Rainier backcountry and ski-tour terrain, even when the app's **Simulate** button stays landslide/debris-flow only.

---

## 5. Lumped-mass (sliding-block) models (Tier B)

### 5.1 Coulomb sled and Voellmy / Voellmy–Salm

**Voellmy (1955)** split basal resistance into dry-Coulomb and velocity-squared "turbulent" terms. RAMMS form (verified):
$$S=\mu N+\frac{\rho g u^{2}}{\xi},\qquad N=\rho h g\cos\phi$$
with $S$ resistance (Pa), $\mu$ dry friction (–), $\xi$ turbulence coefficient (m s⁻²), $\rho$ density, $h$ flow height, $u$ velocity. "μ dominates when the flow is close to stopping, ξ dominates when the flow is running quickly."\[32\]

**Mass-point equation along a path** (standard Voellmy–Salm form ⚠):
$$\frac{dv}{dt}=g(\sin\psi-\mu\cos\psi)-\frac{g\,v^{2}}{\xi\,h}$$
Terminal speed on a long uniform slope:
$$v_\infty=\sqrt{\xi\,h\,(\sin\psi-\mu\cos\psi)}$$

**Integrate along $s$** per segment $\Delta s$:
$$v_{i+1}^2 = v_i^2 + 2\Delta s\left[g(\sin\psi_i-\mu\cos\psi_i) - \frac{g v_i^2}{\xi h}\right]$$
Stop where $v^2\le0$.

### 5.2 Perla–Cheng–McClung (PCM, 1980)

- **Citation:** J. Glaciol. 26(94):197–207, doi:10.3189/S002214300001073X.\[34\]\[35\]

Closed-form segment solution (as used in Flow-R and GPP, verified from Horton et al. 2013):\[14\]
$$V_i=\left(a_i\,\omega\,(1-e^{b_i})+V_0^2e^{b_i}\right)^{1/2},\quad a_i=g(\sin\beta_i-\mu\cos\beta_i),\quad b_i=\frac{-2L_i}{\omega}$$
with $\omega=M/D$, $L_i$ segment length, $V_0$ entry speed. Apply $V'_i=V_i\cos(\beta_i-\beta_{i+1})$ at abrupt slope decreases.\[14\]

### 5.3 Snow-avalanche parameter defaults

| Source | μ | ξ (m s⁻²) | Context |
|---|---|---|---|
| Voellmy (1955) | ~0.08–0.15 (density-dependent) | ≈500 "rough stream course" | Original suggestions |\[37\]
| Buser & Frutiger (1980), J. Glaciol. | 0.155 (fit); **0.16 recommended** | 1120 (fit); **1360 recommended** (mean + 2σ) | 10 extreme Swiss avalanches, hazard zoning |\[37\]
| "Usual" calibration quoted in arXiv:1710.00524 | 0.15 | $g/\xi=0.0049$ → ξ≈2000 | Mass-point comparison |\[33\]
| Gauer (2014), as quoted in arXiv:1710.00524 | 0.4 | $g/\xi=0.00018$ → ξ≈54 500 | Alternative calibration for β≈30° |\[33\]
| RAMMS "MuXi" | Varies with track type, altitude, return period, volume | — | Swiss guidelines (Salm et al. 1990) |\[32\]

Low-μ/moderate-ξ and high-μ/very-high-ξ calibrations can reproduce similar runouts with different velocity histories. Calibrate μ and ξ *as a pair*, never independently.

---

## 6. Depth-averaged models (Tier C — offline only)

RAMMS (Christen, Kowalski & Bartelt 2010) is the Swiss operational standard for **dense snow avalanches** in 3-D terrain; it uses Voellmy friction and was calibrated at Vallée de la Sionne.\[40\]\[32\] AvaFrame **com1DFA** (Tonnel et al. 2023) is the open thickness-integrated avalanche kernel used with com2AB and com4FlowPy in one framework.\[45\]\[46\] These solvers need release depth, rheology, and CFL-limited time stepping — use them to validate or calibrate Tier A/B on mountain DEMs, not inside the live Simulate loop.

---

## 10. Recommended TerraSense architecture (tiered)

### Tier A — real-time extent (browser Web Worker or light backend)

**Default parameters to start from (then calibrate):**

| Process | α (reach angle) | exponent | persistence | $Z^\delta_{max}$ / $V_{max}$ | $R_{stop}$ | Source |
|---|---|---|---|---|---|---|
| **Snow avalanche** | from α–β: $0.96\beta-1.4^\circ$ (−1 SD conservative) | **8** | Flow-Py cosine | $Z^\delta_{max}=V_{max}^2/2g$ | ~$3\times10^{-4}$ | AvaFrame docs; Bakkehøi et al. 1983; Horton et al. 2013 |
| Debris flow | 11° coarse/medium; 7° fine | 4–6 (modified Holmgren $dh$≈2 m on fine DEMs) | Flow-R proportional/cosine | $V_{max}=15\ \mathrm{m\,s^{-1}}$ → $Z^\delta_{max}\approx11.5$ m | $3\times10^{-4}$ (10 m) | Horton et al. 2013 |

### Tier B — speed/intensity profile along the dominant path

1. Extract the centreline from Tier A (follow maximum $R$ downstream).
2. Resample at $\Delta s\approx dx$.
3. Run the PCM closed form or the Voellmy $v^2$ update; clip with $V_{max}$.
4. Report peak speed, time to reach trail points, and stop position.

Defaults: **snow** $\mu=0.16$, $\xi=1360$, $h\approx1$ m (Buser & Frutiger 1980); debris flow: calibrate $\mu$ and $M/D$ with Flow-R's sensitivity procedure.

---

## 11. Validation and sensitivities (mountains)

- **DEM resolution.** Flow-R: 10 m optimal; 25–50 m over-spreads.\[14\] RAMMS: DEM quality strongly affects results (Bühler et al. 2011).\[44\]
- **Forest** reduces **avalanche** and rockfall runout; com4FlowPy and AutoATES include forest terms. DEM-only runs are valid only for open terrain.\[28\]
- **Parameter trade-offs.** μ–ξ pairs are non-unique (Section 5.3). Regional parameter transfer is AutoATES's main stated limitation.\[28\]
- **Benchmarks:** AutoATES (Bow Summit, Connaught Creek, CA);\[31\] RAMMS (Vallée de la Sionne);\[90\]

---

## 12. Safety and product caveats (must appear in the UI)

- TerraSense runout layers are **illustrative susceptibility estimates from simplified empirical models**. They are not hazard maps or forecasts, and **not a substitute for official hazard assessments, avalanche bulletins or land-manager closures**.
- The models do not know current snowpack, soil moisture, rainfall or seismicity. Susceptibility does not include timing or probability of occurrence (Horton et al. 2013).\[14\]
- Defaults come from Alpine and Canadian calibrations. Show the parameter set and DEM resolution; prefer conservative (longer-runout) settings.
- Link users to the local **avalanche centre**, geological survey, or park authority (e.g. NWAC for Washington).

---

## 13. Caveats about this document

- ⚠ items are textbook forms or second-hand; verify before production use.
- Software licences were **not** verified. GMD/NHESS *articles* are CC BY, which does not license the *code*. RAMMS is proprietary; cite for comparison only.

---

## 14. References and credits

**Empirical / geometric**
- Heim, A. (1932). *Bergsturz und Menschenleben*. Fretz & Wasmuth, Zürich.
- Scheidegger, A.E. (1973). On the prediction of the reach and velocity of catastrophic landslides. *Rock Mechanics* 5(4):231–236. doi:10.1007/BF01301796\[91\]
- Corominas, J. (1996). The angle of reach as a mobility index for small and large landslides. *Can. Geotech. J.* 33(2):260–271. doi:10.1139/t96-005\[4\]
- Lied, K. & Bakkehøi, S. (1980). Empirical calculations of snow-avalanche run-out distance based on topographic parameters. *J. Glaciol.* 26(94):165–177. doi:10.3189/S0022143000010704\[6\]
- Bakkehøi, S., Domaas, U. & Lied, K. (1983). Calculation of snow avalanche runout distance. *Ann. Glaciol.* 4:24–29.\[93\]
- McClung, D.M. & Lied, K. (1987). Statistical and geometrical definition of snow avalanche runout. *Cold Reg. Sci. Technol.* 13(2):107–119. doi:10.1016/0165-232X(87)90049-8 ⚠
- Gauer, P., Kronholm, K., Lied, K., Kristensen, K. & Bakkehøi, S. (2010). Can we learn more from the data underlying the statistical α–β model with respect to the dynamical behavior of avalanches? *Cold Reg. Sci. Technol.* 62(1):42–54. doi:10.1016/j.coldregions.2010.02.001

**Flow routing / GIS runout**
- Holmgren, P. (1994). Multiple flow direction algorithms for runoff modelling in grid based elevation models: an empirical evaluation. *Hydrol. Process.* 8(4):327–334. doi:10.1002/hyp.3360080405\[96\]
- Horton, P., Jaboyedoff, M., Rudaz, B. & Zimmermann, M. (2013). Flow-R, a model for susceptibility mapping of debris flows and other gravitational hazards at a regional scale. *NHESS* 13:869–885. doi:10.5194/nhess-13-869-2013. https://www.flow-r.org
- O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage networks from digital elevation data. *CVGIP* 28(3):323–344. doi:10.1016/S0734-189X(84)80011-0 ⚠
- D'Amboise, C.J.L., Neuhauser, M., Teich, M., Huber, A., Kofler, A., Perzl, F., Fromm, R., Kleemayr, K. & Fischer, J.-T. (2022). Flow-Py v1.0: a customizable, open-source simulation tool to estimate runout and intensity of gravitational mass flows. *GMD* 15:2423–2439. doi:10.5194/gmd-15-2423-2022\[18\]
- Toft, H.B., Sykes, J., Schauer, A., Hendrikx, J. & Hetland, A. (2024). AutoATES v2.0: Automated Avalanche Terrain Exposure Scale mapping. *NHESS* 24:1779–1793. doi:10.5194/nhess-24-1779-2024. https://github.com/AutoATES \[28\]\[97\]
- Sykes, J., Toft, H., Haegeli, P. & Statham, G. (2024). Automated ATES mapping – local validation and optimization in western Canada. *NHESS* 24:947–971. doi:10.5194/nhess-24-947-2024\[97\]

**Lumped mass and friction**
- Voellmy, A. (1955). Über die Zerstörungskraft von Lawinen. *Schweiz. Bauzeitung* 73:159–165, 212–217, 246–249, 280–285.\[98\]
- Perla, R., Cheng, T.T. & McClung, D.M. (1980). A two-parameter model of snow-avalanche motion. *J. Glaciol.* 26(94):197–207. doi:10.3189/S002214300001073X\[34\]
- Buser, O. & Frutiger, H. (1980). Observed maximum run-out distance of snow avalanches and the determination of the friction coefficients μ and ξ. *J. Glaciol.* 26(94).\[37\]
- Salm, B., Burkard, A. & Gubler, H. (1990). Berechnung von Fliesslawinen. EISLF Mitteilung 47.\[99\]
- Comments on avalanche flow models based on the concept of random kinetic energy (2017). arXiv:1710.00524 (source for the Gauer 2014 calibration ⚠).\[33\]

**Depth-averaged (validation)**
- Christen, M., Kowalski, J. & Bartelt, P. (2010). RAMMS: Numerical simulation of dense snow avalanches in three-dimensional terrain. *Cold Reg. Sci. Technol.* 63(1–2):1–14. doi:10.1016/j.coldregions.2010.04.005. https://ramms.slf.ch \[40\]
- Bühler, Y., Christen, M., Kowalski, J. & Bartelt, P. (2011). Sensitivity of snow avalanche simulations to digital elevation model quality and resolution. *Ann. Glaciol.* 52(58):72–80. doi:10.3189/172756411797252121 \[44\]
- Tonnel, M., Wirbel, A., Oesterle, F. & Fischer, J.-T. (2023). AvaFrame com1DFA (v1.3): a thickness-integrated computational avalanche module – theory, numerics, and testing. *GMD* 16:7013–. https://docs.avaframe.org \[45\]

**Also credited (cited second-hand in the sources above):** Techel et al. (2016, 2018); Birkeland et al. (2017); Schweizer & Lütschg (2001); Techel & Zweifel (2013); Engeset et al. (2018) — via Toft et al. 2024. Veitinger et al. (2016); Sharp (2018) — via AutoATES. Wagner (2016, BOKU MSc) — via AvaFrame com2AB. Huber et al. (2016, 2024 ISSW) — via AvaFrame com4FlowPy.

## Sources

1. [2014 Canadian Geotechnical Colloquium: Landslide runout analysis — current practice and challenges](https://cdnsciencepub.com/doi/10.1139/cgj-2016-0104)
2. [On the prediction of the reach and velocity of catastrophic landslides - ADS](https://ui.adsabs.harvard.edu/abs/1973RMRE....5..231S/abstract)
4. [The angle of reach as a mobility index for small and large landslides](https://cdnsciencepub.com/doi/abs/10.1139/t96-005)
6. [Empirical Calculations of Snow–Avalanche Run–out Distance Based on Topographic Parameters | Journal of Glaciology](https://www.cambridge.org/core/journals/journal-of-glaciology/article/empirical-calculations-of-snowavalanche-runoutdistance-based-on-topographic-parameters/661F331BA0C1E067BB1C9FAB2106EC8A)
7. [Calculation of Snow Avalanche Runout Distance | Annals of Glaciol.](https://www.cambridge.org/core/journals/annals-of-glaciology/article/calculation-of-snow-avalanche-runout-distance/CD6BE1FFFE9F69969E8C67ED0E8A4FD8)
8. [com2AB: Alpha Beta Model — AvaFrame documentation](https://docs.avaframe.org/en/latest/moduleCom2AB.html)
9. [Statistical avalanche-runout estimation for short slopes in Canada | Ann. Glaciol.](https://www.cambridge.org/core/journals/annals-of-glaciology/article/statistical-avalancherunout-estimation-for-short-slopes-in-canada/41E7F12149C24F6506846D15E0B235F5)
10. [com2AB: Alpha Beta — AvaFrame documentation](https://docs.avaframe.org/en/v0.3/moduleCom2AB.html)
11. [com2AB: Alpha Beta Model — AvaFrame documentation](https://avaframe.readthedocs.io/en/1.9_rc2/moduleCom2AB.html)
12. [Statistical and geometrical definition of snow avalanche runout - ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/0165232X87900498)
13. [core reader](https://www.cambridge.org/core/product/61EB34775C30A11F32E78AC105DF3906/core-reader)
14. [NHESS - Flow-R (PDF)](https://nhess.copernicus.org/articles/13/869/2013/nhess-13-869-2013.pdf)
17. [NHESS - Flow-R HTML](https://nhess.copernicus.org/articles/13/869/2013/nhess-13-869-2013.html)
18. [Flow-Py v1.0 (GMD 2022)](https://gmd.copernicus.org/articles/15/2423/2022/)
19. [GMD - Relations - Flow-Py v1.0](https://gmd.copernicus.org/articles/15/2423/2022/gmd-15-2423-2022-relations.html)
20. [com4FlowPy theory — AvaFrame documentation](https://docs.avaframe.org/en/latest/theoryCom4FlowPy.html)
28. [AutoATES v2.0: Automated Avalanche Terrain Exposure Scale mapping](https://nhess.copernicus.org/articles/24/1779/2024/)
29. [(PDF) AutoATES v2.0](https://www.researchgate.net/publication/380757663_AutoATES_v20_Automated_Avalanche_Terrain_Exposure_Scale_mapping)
30. [NHESS - Machine learning for automated ATES classification](https://nhess.copernicus.org/articles/25/4375/2025/)
31. [AutoATES v2.0 – SFU Avalanche Research Program](https://sfuarp.ca/publications/2024_toftothers_autoates/)
32. [Friction Parameters - WSL - RAMMS](https://ramms.slf.ch/en/modules/avalanche/theory/friction-parameters.html)
33. [Comments on avalanche flow models based on the concept of random kinetic energy](https://arxiv.org/pdf/1710.00524)
34. [A Two–Parameter Model of Snow–Avalanche Motion | Journal of Glaciology](https://www.cambridge.org/core/journals/journal-of-glaciology/article/twoparameter-model-of-snowavalanche-motion/B87923FFC6ADAF61B0079EEBCBD96F19)
35. [The Landslide Velocity](https://arxiv.org/pdf/2103.10939)
37. [Observed Maximum Run-Out Distance of Snow Avalanches… | Journal of Glaciology](https://www.cambridge.org/core/journals/journal-of-glaciology/article/observed-maximum-runout-distance-of-snow-avalanches-and-the-determination-of-the-friction-coefficients-and/3D2C036E5671A47F51A90B0ADD4D4B82)
40. [RAMMS: Numerical simulation of dense snow avalanches in three-dimensional terrain - ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0165232X10000844)
44. [RAMMS::Avalanche DEM sensitivity](https://typolive03-microsite-preview.wsl.ch/ramms/en/modules/avalanche/)
45. [(PDF) Avaframe com1DFA (version 1.3)](https://www.researchgate.net/publication/367179045_Avaframe_com1DFA_version_13_a_thickness_integrated_computational_avalanche_module_-_Theory_numerics_and_testing)
46. [com1DFA: DFA-Kernel — AvaFrame documentation](https://docs.avaframe.org/en/ps_docadaptsfc/moduleCom1DFA.html)
90. [RAMMS: numerical simulation… | DORA WSL](https://www.dora.lib4ri.ch/wsl/islandora/object/wsl:3731)
91. [Scheidegger 1973 - Crossref](https://api.crossref.org/works?query.bibliographic=Scheidegger+1973+prediction+reach+velocity+catastrophic+landslides&rows=2&select=DOI,title,author,container-title,volume,issue,page,issued)
93. [Empirical α–β runout modelling… Catalan Pyrenees | J. Glaciol.](https://www.cambridge.org/core/journals/journal-of-glaciology/article/empirical-runout-modelling-of-snow-avalanches-in-the-catalan-pyrenees/BDAD08E2FEF6DF9EF581A1EABBAE0251)
96. [Holmgren (1994) — Crossref lookup](https://api.crossref.org/works?query.bibliographic=Holmgren+1994+Multiple+flow+direction+algorithms+runoff+modelling+grid+based+elevation+models&rows=1&select=DOI,title,author,container-title,volume,issue,page,issued)
97. [NHESS - Relations - AutoATES v2.0](https://nhess.copernicus.org/articles/24/1779/2024/nhess-24-1779-2024-relations.html)
98. [Surface oscillations in channeled snow flows](https://arxiv.org/pdf/0707.2507)
99. [Calculating dense-snow avalanche runout using a Voellmy-fluid model… | J. Glaciol.](https://www.cambridge.org/core/journals/journal-of-glaciology/article/calculating-densesnow-avalanche-runout-using-a-voellmyfluid-model-with-activepassive-longitudinal-straining/D095014CE1A7C4F3DFF3CD3904A2510C)
