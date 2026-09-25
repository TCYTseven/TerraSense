# Design addendum

The design decisions that the spec and UX.md leave open, closed for this build.

[TerraSense.md](TerraSense.md) sets the tokens under [Design Language](TerraSense.md#design-language). [UX.md](UX.md) decides whether a control belongs on screen. [implementation-steps.md](implementation-steps.md) sets the build order. This file picks among the options the spec lists and specifies the details none of them state. It extends those files. It does not repeat them, and it adds no screen, control, or layer that UX.md does not list.

## Precedence

- **Color.** When this file and the spec disagree about a color, the spec wins. Hex values live only in Design Language. This file names each color by its role there.
- **Controls.** When this file and UX.md disagree about whether a control, layer, or screen ships, UX.md wins.
- **Motion.** UX.md rule 10 is the complete list. This file sets durations and easing for the items on it and adds none.
- **Build order.** implementation-steps.md owns the order. Where a step conflicts with the spec or UX.md, the table below records the resolution.
- **References.** A Claude Design bundle, a mockup, or a screenshot is a reference. A decision exists once it is written here.

**Conflicts resolved here**

| Source | Says | Resolution |
|---|---|---|
| implementation-steps.md, step 2 | Lists the original neutral and accent hex values | Use the current values in Design Language. Step 2's hex values are out of date. |
| implementation-steps.md, step 13 | The susceptibility ramp runs from blue-green to red | Use the four risk colors only. Blue-green is not a risk color, and it reads as the accent (UX.md rule 1). |
| implementation-steps.md, step 16 | Susceptibility fades in over 400 ms | It appears at once. Rule 10 lists only the heat map fade. |
| Spec 6.1 | Globe markers are green, amber, or red | Markers use all four levels through [Risk mapping](#risk-mapping). |
| Design Language, Copy | The hiker example runs three sentences | One sentence plus the bypass, per spec 6.6 and UX.md rule 6. See [Copy](#copy). |
| Spec 6.1, step 9 | A marker click flies into the mountain page | A click opens the [mountain panel](#mountain-panel) over the globe (team decision, Sep 25, 2026). **Open ranger view** runs the fly-in. |
| Spec Out of Scope | No simulation mode | Out of scope still means a rain what-if. The [runout simulation](#simulation) has no inputs and replays today's worst slope (team decision, Sep 25, 2026). |

## Direction

The globe and the heat map are the two loud moments. Everything else stays quiet so they land.

- Neutrals are warm stone; the accent is glacier ice. The earth comes from the neutrals and the map, the tech from one cold accent.
- Flat surfaces. No shadows. No gradients except the globe backdrop. No cards inside the panel.
- Surfaces separate by the spec's 1 px panel border. A heavier stroke always carries meaning: selection, severity, or status.
- Color is information. Risk colors mean risk. The accent means "you can press this." Everything else is text or muted text.
- The hiker card is the one soft surface: more space, bigger type, fewer lines.

## Decisions to confirm

Lines tagged **[confirm]** are defaults. Confirm or change each one, then delete the tag. Untagged lines follow from the spec or UX.md.

| Decision | Default | Section | Needed by |
|---|---|---|---|
| Type pair | Space Grotesk and JetBrains Mono | [Type](#type) | Step 2 |
| Display units | Miles, feet, inches | [Units and numbers](#units-and-numbers) | Step 2 |
| Raster alphas | Low transparent, then 0.40, 0.55, 0.70 | [Raster layers](#raster-layers) | Step 13 |
| Globe texture | Dark day-side Earth, no night lights | [Globe](#globe) | Step 8 |
| Search position | Top center | [Globe](#globe) | Step 9 |
| Return to the globe | The wordmark, with the fly-to reversed | [Globe](#globe) | Step 9 |
| Fly-to split | About 0.9 s on the globe, 0.6 s on the map | [Motion](#motion) | Step 9 |
| Basemap | Unlabeled satellite, dimmed | [Basemap and camera](#basemap-and-camera) | Step 15 |
| One raster at a time | Susceptibility hides probability while on | [Raster layers](#raster-layers) | Step 16 |
| Hazard block placement | Under overall risk, opens with the pin | [Sections](#sections-top-to-bottom) | Step 23 |
| High and Extreme treatment | 3 px left border and an 8% tint | [High and Extreme](#high-and-extreme) | Step 23 |
| Static mountains | Hide everything that implies analysis | [Static mountains](#static-mountains) | Step 23 |
| Reasoning panel | Over the map, beside the ranger panel | [Reasoning panel](#reasoning-panel) | Step 23 |
| Narrow layout | Stack below 768 px | [Layout](#layout) | Step 25 |
| Mountain panel size | 60/40 split, `min(1200px, 100vw − 64px)` by `min(760px, 100vh − 128px)` | [Panel frame](#panel-frame) | Step 29 |
| Globe while the panel is open | Turned to face the mountain at altitude 1.2, spin paused, 60% scrim | [Panel frame](#panel-frame) | Step 29 |
| Pressure point count | Up to five, worst first | [Pressure points](#pressure-points) | Step 26 |
| Flow color | Stepped on the risk ramp, heat map dimmed to 35% under it | [Simulation map](#simulation-map) | Step 30 |
| Playback length | One frame every 500 ms, at most 40 frames (20 s) | [Motion](#motion) | Step 30 |
| Callout count | Two to four: at least one for rangers and one public notice | [Callouts](#callouts) | Step 28 |

## Which step reads what

| Section | Steps | Track |
|---|---|---|
| Tokens, Type, Units and numbers, Risk mapping | 2 | Frontend |
| Raster layers | 13, 18 | ML and data |
| Globe, Motion | 8, 9 | Frontend |
| Map | 15, 16, 18, 19 | Frontend |
| Copy | 20, 21 | Backend and agents |
| Review sheet | Before 23 | Frontend |
| Panel, States | 23 | Frontend |
| Hiker card, States | 25 | Frontend |
| Pressure points | 26 | ML and data |
| Simulation map, Copy (steps) | 27 | ML and data |
| Callouts, Copy | 28 | Backend and agents |
| Mountain panel, Panel frame, Pressure points, States | 29 | Frontend |
| Simulation, Motion, States | 30 | Frontend |

## Tokens

Step 2 sets these in `frontend/app/globals.css`. shadcn/ui reads the same variable names, so its components pick up the theme without per-component overrides.

| Variable | Value | Used for |
|---|---|---|
| `--background` | Background, dark end | Page, globe backdrop edge, map fog |
| `--muted` | Background, light end | Inset fields, skeleton bars, globe backdrop center |
| `--card`, `--popover`, `--secondary` | Panels | Side panel, toggle group, hover card, popups, search results |
| `--foreground`, and every `*-foreground` not listed below | Text | Body text |
| `--muted-foreground` | Muted text | Labels, secondary lines, waiting states |
| `--primary`, `--ring` | Interactive accent | Primary button, focus rings, selected states, toggles when on |
| `--primary-foreground` | Background, dark end | Text on the accent |
| `--border`, `--input` | Text at 10% | Every 1 px border |
| `--accent` | Text at 6% | shadcn's hover surface for list rows. Not the cyan |
| `--destructive` | Text | Error text |
| `--risk-low`, `--risk-moderate`, `--risk-high`, `--risk-extreme` | The four risk colors | See [Risk mapping](#risk-mapping) |
| `--radius` | 6px | Controls |

1. **Do not give the cyan to shadcn's `--accent`.** shadcn paints menu and list hovers with it, and cyan hovers would flood the screen.
2. **Errors never borrow risk red.** That is why `--destructive` is the text color.
3. **Radius follows hierarchy.** Controls 6 px. Surfaces floating over the map or globe 8 px. The side panel is square and flush to the viewport edge.
4. **Risk colors are defined in three files and nowhere else:** `globals.css` for Tailwind classes, `frontend/lib/risk.ts` for Mapbox paint and three.js (neither can read CSS variables), and `ml/scripts/render_tiles.py` for the raster ramp. Each copies its values from Design Language.
5. **Neutral and accent values are defined in globals.css and frontend/lib/theme.ts, and nowhere else.** The two files must match. theme.ts exists for Mapbox and three.js, which can't read CSS variables.

## Type

**[confirm]** UI text in **Space Grotesk**. Values in **JetBrains Mono**. Both are on the spec's list.

Geist is the create-next-app default, so a Geist screen reads as a starter template to judges who see dozens of Next.js builds. Inter is the most common UI face there is. Space Grotesk grew out of a monospace design, so it sits naturally beside a mono and gives the dispatch screen an instrument feel. Load both with `next/font/google`: Space Grotesk 400, 500, and 600; JetBrains Mono 400 and 500.

| Role | Size / line height (px) | Weight | Face |
|---|---|---|---|
| Wordmark | 16 / 20 | 600 | Sans, tracking −0.01em |
| Panel title (mountain name) | 24 / 28 | 600 | Sans, tracking −0.01em |
| Lead (risk sentence) | 16 / 24 | 400 | Sans |
| Body (panel rows, hazard values, agent names) | 14 / 20 | 400 | Sans |
| Meta (labels, hover card, toggles, popups, status lines) | 12 / 16 | 400 | Sans |
| Button | 14 / 20 | 500 | Sans |
| Hiker level | 36 / 40 | 600 | Sans, tracking −0.02em |
| Hiker sentence | 21 / 30 | 400 | Sans |
| Hiker bypass name | 18 / 24 | 600 | Sans |
| Hiker bypass values | 16 / 24 | 400 | Mono |

1. **Mono sets values only:** a number with its unit, such as `3.2 mi`, `0.82`, or `12 min`. Words, level names, and labels stay in the sans. Copy strings elsewhere in this file follow the same rule when rendered.
2. **Mono runs at 0.92em** of the surrounding size. JetBrains Mono has a tall x-height and looks a size larger otherwise.
3. **Sentence case everywhere in the UI.** No all-caps labels and no letter-spaced eyebrows. Ranger copy keeps the capitalized level from the spec example.

## Units and numbers

**[confirm]** Display US customary units. Mount Rainier is a US park, and its rangers and hikers read miles and feet. The database and API stay as they are (`length_km`, `elevation_gain_m`, `start_mile`). `frontend/lib/format.ts` converts, and nothing else formats a number.

| Quantity | Format | Example |
|---|---|---|
| Trail distance, mile marker | Miles, one decimal | 3.2 mi |
| Mile range in UI rows | "mi", then the range with an en dash | mi 4.2–5.1 |
| Mile range in sentences | Spelled out | mile 4.2 to 5.1 |
| Added distance | Signed miles, one decimal | +1.2 mi |
| Added climb | Signed feet, nearest 10 | +350 ft |
| Elevation | Feet, nearest 10, thousands comma | 14,410 ft |
| Rain | Inches, two decimals | 1.84 in |
| Probability, confidence, trail score | 0 to 1, two decimals, no percent | 0.82 |
| Time since | Largest whole unit | 12 min ago |
| Clock time | 24-hour local, no seconds | 14:05 |

The Alert Writer prompt (step 20) uses the same formats.

## Risk mapping

| `RiskLevel` | Word | Color in Design Language |
|---|---|---|
| `low` | Low | Green |
| `moderate` | Moderate | Amber |
| `high` | High | Orange |
| `extreme` | Extreme | Red |

1. **Color never carries the level alone.** On the panel and the hiker card, every risk color sits beside its level word. The map's colors match those words, so the map gets no legend.
2. **Risk color appears only on** globe markers, trail lines, the two raster layers, the hazard polygon and pin, pressure point pins and chips, the simulated flow and its trail marks, level words, and the High and Extreme treatment. Never on agent status, simulation steps, callouts, success or error lines, buttons, or historical pins.
3. **No level, no color.** A live mountain with no hazard yet (no finished run and no preview hazard from step 18) shows muted text and "Not analyzed yet." Rainier's seeded placeholder (`moderate`, step 5) never reaches the screen. Static mountains show their seeded level.
4. **`needs_review` keeps the level color** and adds a "Needs review" tag beside the level word: meta size, muted text, 1 px border.

## Globe

Step 8 builds it with `react-globe.gl`. Property names below are that library's.

- **Texture. [confirm]** A dark day-side Earth, for example three-globe's example `earth-dark.jpg`, or NASA Blue Marble darkened and desaturated. At most 4096 × 2048 and under 1 MB, committed as `frontend/public/globe/earth-dark.jpg`. No night-lights texture: city lights are orange and yellow and would read as risk. No bump map, clouds, or starfield. Never hot-link a texture. The venue network is not part of the demo.
- **Atmosphere.** `atmosphereColor` at the text color, `atmosphereAltitude` 0.12. Not the accent: the glow is not interactive.
- **Backdrop.** A radial gradient behind a transparent globe canvas: background light end at the center, dark end at the edges. This is the only gradient in the app.
- **Start view.** Over Mount Rainier (46.85, −121.76) at altitude 2.5. The idle spin starts from there.
- **Markers.** A 10 px dot in the level color, a 2 px ring in the dark background, and a 26 px halo of the level color at 20% alpha. Markers never pulse. Hover shows a pointer and a 2 px accent ring. No permanent labels (UX.md rule 2).
- **Hover card.** Panel surface, border, 8 px radius, 12 px padding, 12 px right of the marker. It appears and disappears at once. Three lines:
  1. The name, body size, 600.
  2. The level dot and word.
  3. For Rainier, "Updated 12 min ago" or "Not analyzed yet." For a static mountain, "Display marker. Not analyzed live." (UX.md rule 8).
- **Wordmark. [confirm]** "TerraSense" at the top left, 24 px in. On the mountain page it stays at the top left over the map, on a panel-surface pill with an 8 px radius, and a click returns to the globe. This is demo step 7's return to the globe.
- **Click.** A marker click or a search pick opens the [mountain panel](#mountain-panel). It no longer routes straight to the mountain page.
- **Search. [confirm]** Top center, level with the wordmark. 360 px wide, 40 px tall, inset surface, border, 6 px radius. Placeholder "Search mountains". Typing lists up to three matching names below the field on a panel surface. Enter opens the top match, a click opens the chosen one, and arrow keys move through the list. Search stays above the scrim while the panel is open, and a pick swaps the panel to that mountain.

## Mountain panel

Added at the team's direction on Sep 25, 2026 (UX.md, Mountain panel). It is the first view of any mountain: a click on the globe opens it, and **Open ranger view** leaves it for the mountain page. It reuses the tokens, type, glyphs, and level treatments below. It adds no new color, face, or radius.

### Panel frame

- **Globe behind it. [confirm]** The click turns the globe to face the mountain at altitude 1.2 (about 0.9 s, ease-in-out, the first leg of the [fly-to](#motion)). The spin pauses, and a flat scrim in the dark background at 60% covers the globe. The panel then appears at once. The wordmark and search stay above the scrim.
- **Size. [confirm]** Centered, `min(1200px, 100vw − 64px)` wide and `min(760px, 100vh − 128px)` tall, never closer than 80 px to the top so the wordmark row stays clear. Panel surface, 1 px border, 8 px radius (it floats over the globe), no shadow.
- **Split.** The map takes the left 60%. The right column takes 40%, at least 380 px, with a 1 px left border, 20 px side padding, and its own scroll. Its footer is pinned to the bottom, like the ranger panel's.
- **Narrow, below 768 px.** The panel fills the screen under the wordmark row with a square edge. The map is on top at 45% of the viewport height, the right column below it.
- **Close.** A close button (X, top right of the right column), Escape, or a click on the scrim. Closing restores the spin at once from the current view. Focus moves into the panel when it opens and back to the marker or search when it closes.
- **Address.** The panel adds `?m=<slug>` to `/` with a shallow route change, so a reload reopens it. Closing removes it.

### Panel map

The same MapLibre style as the [mountain page](#map), with a smaller frame and fewer layers.

- **Camera.** Fits every pressure point with 48 px of padding, pitch 60, and the bearing that turns the selected point toward the camera. Selecting another point does not move the camera. Drag, scroll, and rotate stay on. No controls beyond the required attribution.
- **Layers.** The probability heat map (with its fade on first show), all trails with the hero trail colored by segment, and the pressure point pins. No toggles, no historical pins, no hazard pin, no bypass.
- **Pressure point pins.** A 24 px circle in the point's level color, a 2 px dark ring, and the point's number in the dark background color at meta size, 600. The selected pin takes the hazard pin's accent ring and 1 px dark outer edge, and its zone gets the 2 px outline in its level color.
- **Static mountains.** Terrain only, framed on the summit.

### Pressure points

The right column before a simulation, top to bottom:

1. **Header.** The mountain name at panel-title size. Elevation and region on one meta line, 12 px apart.
2. **Overall risk.** The level dot and word at lead size, 600, with the [High and Extreme](#high-and-extreme) treatment when it applies. While the heat map is the stand-in, one muted meta line under it: "Heat map is the susceptibility stand-in until Model B lands."
3. **Pressure points. [confirm]** The label "Pressure points", then up to five rows, worst first. Each row:
   - Left, a 16 px chip in the point's level color with its number, matching the pin.
   - First line, body size: where it is (see [Copy](#copy)). Right-aligned on the same line: the level dot, word, and peak value.
   - Second line, meta, muted: the drivers, such as "Slope 38°  60 ft from a channel  Sparse cover", 12 px apart with no separator.
   - The selected row gets a 2 px accent left border and the text color at 4% behind it. A row is a button, and a click selects the point and its pin.
4. **Footer.** **Simulate** and **Open ranger view**. See [Panel actions](#panel-actions).

### Panel actions

- **Simulate.** Primary, styled like **Analyze now**: accent fill, 40 px, full width. It starts the simulation from the selected point. Hidden on static mountains (UX.md rule 8), and disabled with the meta line "Nothing reaches Moderate today, so there's nothing to simulate." when the list is empty.
- **Open ranger view.** Secondary, styled like **Hiker forecast**, 8 px below. It closes the panel and runs the [fly-to](#motion) from the current globe view into `/mountains/[slug]`.
- **Back to pressure points** (simulation only). An accent text button at body size at the top of the column, like the hiker card's back button.
- **Replay** (simulation only). Secondary, in place of **Simulate**, disabled while playing. It restarts playback from the frames already loaded; nothing is recomputed.

### Simulation

After **Simulate**, the right column's content swaps in place, at once. The header row and footer stay. The left map plays the flow.

**Right column, top to bottom**

1. **Back to pressure points.**
2. **Title row.** "Simulating pressure point 1" at body size, 600. Right-aligned on the same line, the simulated clock in mono, such as `T+04:30`.
3. **Method line.** Meta, muted: "Illustrative runout from a travel-angle model on 30 m terrain. Not a forecast of timing." (UX.md rule 11). It never hides.
4. **Steps.** The label "Steps", then one row per step in order. The rows reuse the [agent row](#agent-rows) glyphs: a hollow circle for steps not reached, the 8 px dot with the work pulse for the current step, a check for steps passed. Each row has a title at body size, then a meta line with the simulated time and the step's values, 12 px apart. A trail step adds the level dot and word of the flow where it crosses. Steps never take a risk-colored glyph or background.
5. **Callouts.** The label "Callouts", then each callout as its step is reached. See [Callouts](#callouts).
6. **Status line.** When playback ends: "Simulation finished. The flow ran 1.4 mi and crossed 2 trails." in the status line style from [States](#states).
7. **Footer.** **Replay** and **Open ranger view**.

### Simulation map

- **Flow. [confirm]** The footprint at each frame is a fill on the same stepped ramp as the rasters: intensity below 0.20 transparent, then amber 0.40, orange 0.55, red 0.70. While a simulation shows, the heat map drops to 35% `raster-opacity` at once, so the flow reads on top of it. Back to pressure points restores it.
- **Edge.** A 1.5 px line in the text color at 70% traces the footprint's current edge. It is geometry, not a level, so it is not a risk color.
- **Trail marks.** Where the flow first crosses a trail, a 20 px version of the hazard pin (level color, dark ring, warning triangle) appears when that step is reached. The crossed miles of the hero trail keep their segment colors.
- **Camera.** It does not move during playback. If the final footprint falls outside the frame, fit its bounds with `duration: 0` before playback starts.
- **Other pins.** Pressure point pins other than the source hide while a simulation shows.

### Callouts

Two to four notes from the AI, one model call routed like the agents (see [Copy](#copy) for wording). **[confirm]** At least one for rangers and one public notice.

- Each callout sits under the "Callouts" label: a meta line with the audience on the left and the step's simulated time in mono on the right, then the text at body size. A 2 px left border in the text color at 40% runs beside it. No fill, no card, no accent, no risk color.
- Audience labels: "Rangers" and "Public notice, draft, not sent". The public label never shortens.
- A callout appears at once when playback reaches its step. Under reduced motion, all of them show at once.
- While the model call is out, one meta line reads "Writing callouts…" with the work pulse. If the call fails, code templates stand in and the status line adds "Callouts came from templates. The AI didn't answer."
- Callouts have no buttons: no send, copy, or share (UX.md, What would make the UX wrong).

## Map

### Basemap and camera

- **Style. [confirm]** `mapbox://styles/mapbox/satellite-v9`: imagery without labels. The panel names the trails, and map labels would compete with trail color.
- **Dimmed imagery. [confirm]** On the satellite layer, `raster-saturation` −0.35 and `raster-brightness-max` 0.8. Risk colors become the most saturated things on screen, and the map sits closer to the dark UI.
- **Terrain.** Exaggeration 1.5 (spec 6.2).
- **Sky.** `setFog` with `color`, `high-color`, and `space-color` at the dark background, `horizon-blend` 0.08, `star-intensity` 0. The default Mapbox sky is light blue, a color the spec does not have.
- **Default camera.** Centered on the flagged drainage, zoom about 12, pitch 55. Step 18 picks the bearing so the drainage faces the camera and the bypass sits in frame. Record the center, zoom, and bearing here when step 18 is done.
  - *Recorded at step 18:* the map keeps step 15's opening frame, the summit plus the Skyline loop fitted with 150 px of top padding, pitch 55, bearing -14 (about zoom 12.2 at 1440 x 900). The flagged miles move with each run, and every one of them, with any bypass, sits on or inside the loop, so one frame serves every run.
- **Controls.** None beyond the attribution and logo that Mapbox's terms require. No navigation, fullscreen, or geolocate control. Drag, scroll, pinch, and rotate stay on.

### Raster layers

Probability (the default layer, step 18) and susceptibility (step 16) share one stepped ramp on the spec's bins. **[confirm]** the alphas.

| Value | Color | Alpha |
|---|---|---|
| Below 0.20 | None | 0 |
| 0.20 to 0.45 | Amber | 0.40 |
| 0.45 to 0.70 | Orange | 0.55 |
| Above 0.70 | Red | 0.70 |

1. **Low is transparent.** A mountain painted green buries the hazard. Green stays on trails, where "this segment is fine" is the useful message.
2. **Stepped, not blended,** so every color on the map equals a level word in the panel.
3. **Susceptibility uses the same edges.** If the ML owner moves them for Model A, record the new edges here.
4. **Color and alpha are baked into the PNG tiles.** `raster-opacity` stays at 1 except during the heat map fade. Set `raster-fade-duration` to 0 on both layers so tile loads add no fade of their own. On 3D terrain MapLibre caches draped layers as textures that ignore paint changes, so the fade redraws them each frame (`terrain-map.tsx`).
5. **One raster at a time. [confirm]** Turning Susceptibility on hides probability. Turning it off brings probability back. The same ramp stacked twice cannot be read.

### Trails, bypass, and pins

- **Trail line.** 3 px at zoom 11, rising to 6 px at zoom 15, colored by segment level. A casing 2 px wider in the dark background runs underneath so the line reads on snow and forest. Round caps and joins. Segments without a level (before step 18) use the text color at 70%.
- **Bypass.** Drawn only while the hiker card is open. Same width, colored by its own segment levels, dashed (2, 1.5). The dash marks the suggested route. The color still means risk.
- **Hazard polygon.** A 2 px outline in its level color. No fill; the raster already fills it.
- **Hazard pin.** A 28 px circle in its level color, a 2 px dark ring, and a 14 px warning triangle (lucide `TriangleAlert`) in the dark background color. When selected, a 2 px accent ring sits outside the dark ring, and a 1 px dark outer edge outside it, so the ring stays visible over snow. One pin only.
- **Historical pins.** 8 px circles in the text color at 85%, with a 1.5 px dark ring. Not a risk color: a past event is not today's level. A click opens a popup with the date, type, and source (step 16) on a panel surface with an 8 px radius and no close button. A click on the map closes it.

### Layer toggles

- Lower left of the map, 16 px in (step 16). Panel surface, border, 8 px radius, 4 px padding.
- Two toggles, stacked, 32 px tall: "Susceptibility" and "Past landslides". Probability is the page's default layer and has no toggle.
- Off: muted text, no border. On: accent text and a 1 px accent border.
- Hidden on static mountains, which have no layers.

## Panel

### Layout

- **Wide, 768 px and up.** Map left, panel right. Panel width `clamp(360px, 30vw, 440px)`, and the map takes the rest (about 70/30, per the spec). The panel is full height with a 1 px left border and scrolls inside itself. **Analyze now** and **Hiker forecast** sit in a footer pinned to the panel bottom, so they stay last in UX.md's order and stay reachable.
- **Narrow, below 768 px. [confirm]** Map on top at 55% of the viewport height, panel below, and the page scrolls. The footer is not pinned.
- 20 px side padding. A 1 px border separates sections, with 16 px above and below each.

### Sections, top to bottom

UX.md sets the order. The hazard block is the one addition, and it shows only while the pin is selected.

1. **Header.** The mountain name at panel-title size. Below it, elevation and region on one line in muted text, 12 px apart, with no separator character.
2. **Overall risk.** The level dot and word at lead size, 600, in the level color. Then the one sentence at lead size.
3. **Hazard. [confirm]** Opens under overall risk when the pin is selected: by a click, or when a run finishes. Four rows in the spec's order, each a meta label over a body value: "What it is", "Why it was flagged", "Confidence", "How to avoid it". "What it is" names the trail and the mile range. A second click on the pin, or a click on the empty map, closes it.
4. **Rain.** The label "Rain", then two rows with words left and values right: "Past 72 hours" and "Next 24 hours". Text only (UX.md rule 7).
5. **Trails.** The label "Trails", then one row per trail: the name left; the level dot, word, and score right. The flagged trail adds a second line, "Flagged mi 4.2–5.1", whether or not the pin is open. The mile range is never hidden.
6. **Agents.** The label "Agents", then the five rows in [Agent rows](#agent-rows).
7. **Status line.** One line under the rows for a finished or failed run. See [States](#states).
8. **Footer.** The two actions.

### High and Extreme

**[confirm]** When the level is High or Extreme, the overall risk section and the hazard block get a 3 px left border in the level color and a background of the level color at 8%. Nothing moves (UX.md rule 10). Low and Moderate get neither.

### Agent rows

Five rows in pipeline order: Terrain, Weather, Trail, Synthesizer, Alert Writer. Terrain and Weather run together, so two rows can run at once. Each row is a 16 px status glyph, the agent name at body size, and the latest `AgentEvent.summary` below it: meta size, muted, one line, truncated with an ellipsis, with the full text in the `title` attribute.

| Status | Glyph | Glyph color | Second line |
|---|---|---|---|
| `waiting` | Hollow circle (lucide `Circle`) | Muted | Waiting |
| `running` | 8 px filled dot | Text | The latest summary, or "Running" |
| `done` | Check (lucide `Check`) | Text | The latest summary |
| `error` | Cross (lucide `X`) | Text | "Failed:" and the summary |
| Skipped after an error | Dash (lucide `Minus`) | Muted | Skipped |

Status never uses a risk color: green for done or red for failed would claim a risk level. The running row gets a background of the text color at 4% and the work pulse (see [Motion](#motion)).

Each row also names the model the router picked for it, such as "Gemini 3.8 Flash", at meta size and muted, right-aligned on the name's line. A row is a button: a click opens the [reasoning panel](#reasoning-panel) on that agent. **Reasoning**, a text button at meta size beside the "Agents" label, opens it on Terrain. When **Analyze now** starts a run, the panel scrolls the rows into view at once.

### Actions

- **Analyze now.** Primary. Accent fill, dark background text, 40 px tall, full width, 6 px radius, Button type role. While a run is in progress it reads "Analyzing…", drops to 40% opacity, and ignores clicks (step 23). Hidden when `is_live` is false (UX.md rule 8).
- **Hiker forecast.** Secondary. No fill, a 1 px accent border, accent text, the same size, 8 px below. Disabled until the first finished run, with the meta line "Available after the first finished run."
- **Hover and focus.** Primary hover lowers the fill to 90% opacity. Secondary hover adds an accent background at 10%. Every control shows a 2 px accent focus ring with a 2 px offset on `focus-visible`. Every state change is instant. Accent text never relies on hue alone. Toggles and the secondary button have borders; text buttons and links are underlined (1 px, 3 px offset).

### Reasoning panel

Added at the team's direction on Sep 25, 2026 (UX.md, Reasoning panel). It explains the agents; it adds no control that changes a run.

- **Placement.** Wide: over the right side of the map, flush against the ranger panel, full height, `min(520px, 100%)` wide, panel surface, a 1 px left border, no radius (it docks to the panel). Narrow: it fills the screen. It appears and closes at once. Escape and the close button (X, top right) close it, and it takes focus when it opens.
- **Header.** "Reasoning" at body size, 600, then one meta line: "A router sends each agent to Gemini Flash or Grok. Pick an agent to see why, what it read, and how it reasoned." and the run's time.
- **Tabs.** One per agent in pipeline order, each with the row's status glyph. The selected tab takes the toggle treatment: accent text and a 1 px accent border.
- **Sections, top to bottom,** each a meta label over body text, separated by the 1 px border: Model (label, tier, the model that actually answered, time, tokens), Why this model (the router's sentence, then each rule with its verdict, "→ Gemini", "→ Grok", or "no change", in a bordered meta tag, then the fallback), What it read (each tool call as code, with its facts behind a disclosure), How it reasoned (the provider's thinking summary as a quote with the 2 px muted rule, then the agent's steps as a numbered list), What the code did, Calls (every attempt with its time and error), Answer (the model's JSON and the payload, behind disclosures).
- **Type.** Tool calls and JSON are code and use the mono face; everything else follows [Type](#type).
- **Color.** No risk colors: this is about the reasoning, not the level. Status glyphs match the agent rows.

### Static mountains

**[confirm]** A static mountain hides everything that implies analysis: **Analyze now** (UX.md rule 8), the agent rows, **Hiker forecast**, and the layer toggles. The panel keeps the header, overall risk with the seeded level, and one sentence: "Display marker. Live analysis runs on Mount Rainier only." The map shows terrain only.

## Hiker card

The card replaces the panel content in place (UX.md). The map stays, and the surface keeps the panel's dark color (Design Language). It is softer than the panel: 28 px padding, no section borders, no labels, and mono only for the bypass values.

1. **Back.** "Back to ranger view", an accent text button at body size. It restores the panel.
2. **Trail name.** Lead size, muted.
3. **Level.** Hiker level size, in the level color. The word only, no number.
4. **Sentence.** Hiker sentence size, text color. The Alert Writer's hiker sentence.
5. **Bypass.** 24 px below the sentence: the bypass name at bypass-name size, then the added distance and added climb as mono values 16 px apart, such as +1.2 mi and +350 ft. The values come from `GET /forecast`, never from the model's text.

The card never shows drivers, weights, AUC, probability, or confidence (UX.md rule 6 and "What would make the UX wrong"). It has no share image and no download (spec 6.6).

While the card is open, the bypass draws dashed, the flagged segment keeps its level color, other trails drop to 35% opacity, and the raster stays. The default camera already frames the flagged segment and the bypass, so the camera does not move. If the bypass falls outside the frame, fit its bounds with `duration: 0`.

Below 768 px the card fills the panel area under the map.

## States

UX.md asks for empty, loading, and error states on every view, and step 25 builds them.

- Status and error lines use meta size, the text color, and a 2 px left border in the text color at 40%. They never use a risk color.
- Skeleton bars use the inset surface and the work pulse.
- A loading line appears only after 500 ms, so fast loads don't flash.
- Copy states what happened and what still works. It does not apologize.

| View | State | What shows | Copy |
|---|---|---|---|
| Globe | Loading mountains | Globe, wordmark, search, no markers | Loading mountains… (under the search field) |
| Globe | API unreachable | Globe keeps spinning, no markers | Can't reach the TerraSense API. Retrying every 5 seconds. |
| Globe | No mountains | Globe, no markers | No mountains in the database. Run the seed script. |
| Globe | Search finds nothing | One line in place of the list | No mountain matches "‹query›". |
| Mountain panel | Loading | Panel frame, map loading, header from the globe's data, skeleton bars for the rows | None |
| Mountain panel | Pressure points fail | Map with the heat map, no pins, Simulate disabled | Couldn't load the pressure points. Open ranger view still works. |
| Mountain panel | No pressure points | Map, empty list, Simulate disabled | Nothing reaches Moderate today, so there's nothing to simulate. |
| Mountain panel | Static mountain | Terrain, header, fixed level, Open ranger view | Display marker. Live analysis runs on Mount Rainier only. |
| Simulation | Starting | Steps listed and not reached, Replay disabled | Tracing the flow… (on the title row, until the first frame) |
| Simulation | Playing | Flow advances, current step pulses, callouts appear | None |
| Simulation | Finished | Final flow stays, all steps checked | Simulation finished. The flow ran 1.4 mi and crossed 2 trails. |
| Simulation | Callouts from templates | As finished | Simulation finished. … Callouts came from templates. The AI didn't answer. |
| Simulation | Failed | Pressure points restored, heat map at full opacity | The simulation didn't run. The pressure points still show. |
| Simulation | Stream lost | Frames already loaded keep playing, missing callouts stay out | Lost the connection. Some callouts may be missing. |
| Mountain | Loading | Map loading; panel header from the globe's data; skeleton bars for risk, rain, and trails | None |
| Mountain | Unknown slug | Panel only | No mountain at this address. Back to the globe (link) |
| Mountain | API unreachable | Map without trails, panel header only | Can't load ‹mountain›. Retrying every 5 seconds. |
| Mountain | Tiles fail | Map without the raster, trails still colored | The heat map didn't load. Trail colors still show segment risk. |
| Mountain | Live, no hazard yet | Muted risk section, no pin, rows waiting, Hiker forecast disabled | Not analyzed yet. Analyze now scores the next 72 hours. |
| Run | Running | Rows update, Analyze now disabled | Analyzing… (on the button) |
| Run | Finished | Pin selected, panel updated, heat map fades in | Finished in 48 s. |
| Run | Finished, needs review | As finished, plus the tag | Finished in 48 s. Agents disagree on severity, so this is an advisory. |
| Run | Failed | Failed row, later rows skipped, last good hazard stays, Analyze now enabled | Run failed at the Weather step. The map still shows the hazard from 14:05. |
| Run | Failed, no earlier hazard | As failed, no pin | Run failed at the Weather step. There's no earlier hazard to show. |
| Run | Stream lost | Treated as failed | Lost the connection to this run. The map still shows the hazard from 14:05. |
| Hiker card | Loading | Card with skeleton bars | None |
| Hiker card | Error | Card with one line | The hiker forecast didn't load. Go back and open it again. |

## Motion

UX.md rule 10 is the complete list. This section sets the values.

| Motion | Value | When |
|---|---|---|
| Idle globe spin | About one turn every 2 minutes (`controls().autoRotateSpeed = 0.5`) | Always on the globe. Pauses on marker hover or drag, and resumes after 3 s idle |
| Fly-to | 1.5 s total, in the sequence below | Marker click or search |
| Heat map fade | `raster-opacity` from 0 to 1 over 600 ms (`raster-opacity-transition`) | When the probability layer first shows, and when new tiles arrive after a finished run |
| Work pulse | Opacity 1 to 0.4 and back, 1.2 s, ease-in-out, repeating. One keyframe, `work-pulse`, used through one class, `animate-work` | Running agent rows, the current simulation step, "Writing callouts…", and skeleton bars only |
| Turn to face | The first leg of the fly-to alone: about 0.9 s, ease-in-out, ending at altitude 1.2 | Marker click or search, before the mountain panel opens |
| Simulation playback | **[confirm]** One frame every 500 ms, at most 40 frames. Each frame replaces the flow at once, with no tween between frames | After **Simulate** and **Replay** |

**Fly-to sequence. [confirm]** the split. **Open ranger view** starts it from the view the panel left, so the first leg is short.

1. The globe camera moves to the mountain at low altitude (`pointOfView`, about 0.9 s, ease-in-out).
2. The route changes. The globe stays mounted under the map (mount it in the root layout), so no blank frame shows.
3. The map opens at the same center with pitch 0 and zero opacity. On its first render it fades to full opacity in 200 ms while it eases to the default camera in about 0.6 s.
4. The globe stops rendering behind the map.

These four parts are one fly-to. Tune the split at step 9 until the last globe frame and the first map frame match. The wordmark runs the same move in reverse, ends at altitude 2.5, and resumes the spin.

**Off, and it stays off**

- shadcn/ui enter and exit animations. Remove `animate-in`, `animate-out`, `fade-*`, `zoom-*`, and `slide-*` classes from every component in `frontend/components/ui`. Replace the Skeleton component's `animate-pulse` with `animate-work`.
- `transition-*` utilities. Hover, focus, open, and close states change instantly.
- Toasts. Status lines live in the panel.
- Marker pulses, number count-ups, and any Mapbox `flyTo` or `easeTo` outside step 3 of the fly-to.
- Panel enter and exit animations, and any camera move on the panel map during playback.

**Reduced motion** (`prefers-reduced-motion: reduce`): no spin. The turn to face and the fly-to become instant. The heat map appears without the fade. The pulse stops, and a running row reads "Running". A simulation shows its final flow, every step checked, and every callout at once, with no playback.

## Copy

Design Language and UX.md rules 5 and 6 set the voice. These templates keep the UI and the Alert Writer (steps 20 and 21) saying the same thing.

- **Ranger line.** `<Hazard> risk <LEVEL>. <Place>, <trail> mile <a> to <b>. Confidence <0.00>.`
  Example: "Debris flow risk HIGH. East fork drainage, Ridge Trail mile 4.2 to 5.1. Confidence 0.82." This adds the trail and mile range to the spec's example, because UX.md never lets the ranger view hide them.
- **Advisory.** When `needs_review` is set, the ranger line starts with "Advisory." and ends with "Confirm on site before closing."
- **Hiker sentence.** One sentence of 25 words or fewer. It names the cause and the bypass. No numbers and no model words ("probability", "confidence", "model", "susceptibility").
  Example: "Days of heavy rain could send mud and rock onto the Ridge Trail above the east fork, so take the Cedar Loop instead."
- **Bypass values** come from the API and render in the card's bypass block. The model never writes them.
- **Pressure point place.** `<Facing>-facing slope above <trail>, mi <a>–<b>` when a trail runs below it within 0.5 mi, else `<Facing>-facing slope, <elevation>`. Example: "SE-facing slope above Skyline Trail, mi 1.2–1.5".
- **Simulation steps.** Code writes them from the runout facts, never the model: "Slope releases", "Flow enters the channel", "Reaches <trail>, mi <a>–<b>", "Flow stops". Meta values: time (`T+02:10`), distance from the release (`0.8 mi`), and drop (`−1,240 ft`).
- **Ranger callout.** One or two imperative sentences, 25 words or fewer. Names the trail and mile range from the steps. Example: "Close Skyline Trail mile 1.2 to 1.5 and hold hikers at the Paradise trailhead until someone checks the channel."
- **Public notice.** One or two plain sentences, 30 words or fewer, for people nearby. Names the trail and the place to avoid. No numbers except mile markers, and no model words. Example: "Mud and rock may cross the Skyline Trail above Paradise. Stay off the trail until rangers reopen it."
- **Callout facts.** Every trail, mile, and time in a callout must match a step. Code checks this like the Alert Writer's copy and uses templates when the model keeps failing.
- **Level words.** "Low", "Moderate", "High", and "Extreme" in the UI. All caps in ranger copy only.
- **UI strings.** Sentence case, plain verbs, no apologies. An action keeps its name through the flow: **Analyze now**, then "Analyzing…", then "Finished". Button labels stay exactly as the spec writes them.

## Review sheet

Before step 23, build one component sheet in Claude Design from this file. It is a review surface, not a spec.

- **On the sheet:** the panel sections in order at Moderate and at High, each agent row status, the hazard block, the toggle group on and off, the hover card, search with results and with no match, the hiker card, the mountain panel's pressure point list with one row selected, the simulation column mid-playback and finished (steps and both callout audiences), and every state in [States](#states) with its copy.
- **Off the sheet:** new screens or controls, the globe (judge it moving, at step 8), and the raster layers (judge them on terrain, at steps 16 and 18).
- The sheet uses this file's tokens and type. It may propose changes only to lines tagged [confirm]. Write accepted changes back here before Claude Code uses the handoff bundle.

## How to check

UX.md's check still holds: run the frontend and walk the demo order. A still screenshot is not the check. Add these:

1. Search `frontend/` and `ml/` for each risk hex from Design Language. Matches appear only in `globals.css`, `frontend/lib/risk.ts`, and `ml/scripts/render_tiles.py`. Search the same folders for each neutral and accent hex. Matches appear only in `globals.css` and `frontend/lib/theme.ts`.
2. `grep -rnE "animate-|transition" frontend/app frontend/components` finds only `animate-work`.
3. Pitch the map to the horizon. The sky matches the background, with no blue.
4. Every risk color on the panel and the hiker card has its level word beside it.
5. A static mountain page shows no **Analyze now**, agent rows, **Hiker forecast**, or toggles.
6. Stop the API mid-run. The failure copy shows, the last good hazard stays, and nothing turns red.
7. Walk the path once with reduced motion on.
8. Click Rainier on the globe: the panel opens over a paused, dimmed globe. Escape closes it and the spin resumes.
9. Run **Simulate** to the end. The method line never hides, every public notice says "draft, not sent", and no callout has a button.
10. Open a static mountain's panel: no pressure points and no **Simulate**.
11. No component uses a Tailwind gray, slate, zinc, neutral, or stone color class.
