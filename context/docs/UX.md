# UX

Why TerraSense has its surfaces, and the rules for adding anything to any of them.

The visual tokens (colors, type, motion) are in [`../TerraSense.md`](../TerraSense.md) under Design Language. This file decides whether a control belongs on screen. When they disagree about a color, the spec wins. When they disagree about whether to add a control, this file wins. [`../design-addendum.md`](../design-addendum.md) sets sizes, copy, and states for everything listed here.

## The problem

A ranger and a hiker need different sentences from the same model.

The ranger is at a desk or in a truck after a storm, deciding whether to close a segment. They can read a panel. They need the trail, the miles, the severity, and why.

The hiker is about to leave, often on a phone, often in a group chat. They need one level and one action: go, or take the other trail.

A heat map alone serves neither person. A paragraph of model features serves neither person. The screen has to end in a label someone can act on.

## The thesis

**The globe is the way in. The mountain panel is the first look: where the mountain can fail, and what happens if it does. The mountain page is a dispatch board for the ranger. The hiker card is the only place that reads like a consumer app.**

The judge demo walks that order on purpose: globe, mountain panel, simulation, mountain page, the five trails, agents and their traces, reactive measures. Each surface has one job. A control that serves a third audience does not ship this weekend.

## Rules

1. **Risk colors mean risk.** Green, amber, orange, and red appear only on markers, trails, heat, the simulated flow, and severity. The accent cyan is the only interactive color.
2. **The globe stays almost empty until a click.** Name, search, globe. Stats, legends, and settings do not go on this screen. A click on a marker opens the mountain panel over it, and closing the panel returns the empty globe.
3. **The mountain page is a map plus one panel.** The map is about 55% of the width and the panel about 45%. Layer toggles sit on the map. **Analyze now** is pinned to the bottom of the panel. **Simulate** sits beside it when the mountain has routes. No other sidebar, drawer, or panel opens on this page.
4. **A hazard explains itself in four lines, in this order.** What it is. Why it was flagged. Confidence. How to avoid it.
5. **Ranger copy is short.** Name the hazard, the place, and the confidence. Skip a lecture.
6. **Hiker copy is one sentence plus the bypass.** Name the bypass, the added distance, and the added climb. Skip probability jargon.
7. **Weather is text in the Weather agent's trace.** The mountain page has no rain section. Weather is never a map layer.
8. **Static mountains do not pretend to analyze.** Hide **Analyze now** when `is_live` is false. Hide **Simulate** when the mountain has no routes. The seed's static peaks have no routes, so they show neither.
9. **A running analysis is visible.** An Orchestrator node and five agent cards, each idle, running, done, or error. The running card moves. A failure says the run failed and leaves the last good hazard on the map.
10. **Motion is short.** Idle globe spin. A slow idle orbit of the mountain on the mountain page, which stops for the user. Fly-to in about 1.5 seconds. Heat map fades in. A simulation plays its flow down the slope. Nothing else animates unless it shows that work is happening.
11. **A simulation says what it is.** It is an illustrative landslide and debris-flow runout from the route most likely to fail, not a forecast of timing and not a snow avalanche. Every public message it shows is a draft that was not sent.

## The screens

### Globe

Full viewport. Dark earth, three markers colored by risk, slow idle rotation, hover card (name, risk, last refresh), and search.

A mountain click or a search pick turns the globe to face the mountain, then opens the mountain panel in the center of the screen. The spin pauses while the panel is open. Built today, that click flies straight into `/mountains/[slug]`.

A hill uses a single-rise glyph. Turtle Mountain is the one hill. Its click uses the same fly-to and opens the hill page. Search matches hills and mountains.

### Mountain panel (team decision, Sep 25, 2026)

One panel, centered over the globe, for every mountain. It closes with Escape, its close button, or a click on the globe around it.

**Left: the mountain.** A 3D terrain map of the mountain with the 72-hour heat map and numbered pins on the pressure points. Trails are drawn and the hero trail is colored by segment. The map has no toggles.

**Right: the pressure points.** The mountain's name and overall level, then up to five pressure points: the slopes most likely to fail, worst first. Each row gives its number, where it is, its level, and the terrain that drives it. A click on a row selects it and its pin. The simulation does not take a selection: it always runs on the one route most likely to fail. The first point is selected when the panel opens.

**Bottom of the right side:** **Open ranger view**, which flies into the mountain page. **Simulate** is not on this panel. As of Sep 26, 2026 it lives on the mountain page, beside **Analyze now**, and only for a mountain that has routes.

**The runout plays on the mountain page, not in this panel.** See [Mountain page](#mountain-page-rebuilt-sep-25-2026).

Static mountains open the same panel with terrain only, their fixed level, and one line saying they are display markers. No pressure points. **Simulate** is not offered, because these peaks have no routes.

### Mountain page (rebuilt Sep 25, 2026)

Two columns at full height. **Left, about 55%:** the 3D mountain view: terrain on a light shaded relief (or Mapbox satellite with a token), the 72-hour heat map by default, toggles for susceptibility and historical pins, trails, and one hazard pin. Each of the top five trails has a letter marker (A to E) on its region. Hovering a marker shows that trail's risk score, slope, and primary risk factor. The opening view frames the whole mountain, sized from its elevation, so any mountain opens the same way. While nobody is using it, the camera slowly orbits the mountain. It can't zoom out more than a third of a zoom level past the opening view. A click on a trail's marker or line on the map does what **View** does: the camera flies there and the trail's row is selected.

**Right, about 45%:** one panel. The header and overall risk stay at the top. Under them are two tabs (Sep 26, 2026), **Prevention** and **Response**. Each tab scrolls on its own and pins its own action to the bottom. The panel opens on Prevention.

1. **Header.** The mountain name and one line of stats: elevation, mean slope, area.
2. **Overall risk.** The score as a number, with the level word and color.
3. **Top 5 at-risk trails.** Riskiest first. Each row: letter, name, score, and **View**, which flies the camera to that trail's region, turned to look up the slope so its face is toward the viewer.
4. **Preventative measures.** Three to five short bullets.
5. **Agents.** An Orchestrator node connected to five cards: Terrain, Weather, Trails, Synthesizer, Mass Alert Writer. A click on a card opens its full reasoning trace directly beneath it, one at a time. After a run, **Reactive Measures** get their own prominent section below the cards. They are clustered by when they have to happen, soonest first: now, within 1 hour, within 6 hours, and within 24 hours. Each measure is labeled with its kind of work (closures and access, evacuation and sweeps, search and rescue readiness, field monitoring, agency coordination, or public notice), and public notices are drafts that were not sent.
6. **Footer.** **Simulate**, when the mountain has at least one route, and **Analyze now**, when the mountain is live. They sit side by side. Mount Rainier has routes and is live, so both show. A peak with no routes does not show **Simulate**.

**Simulate** (Sep 26, 2026) starts an illustrative landslide and debris-flow runout from the route most likely to fail. The camera flies to that route. On the mountain view, a time bar at the top shows the simulated span, and a flow footprint on the map grows downhill in step with that clock. The flow is an area spreading over the terrain, drawn on the ground as dirt: dark brown in its interior from the release down, paling to light brown toward its sides as it spreads downhill. The camera frames the whole runout looking uphill, so the front of the flow comes toward the viewer. The bar is a display of the span. It is not a scrubber, a speed control, or a rain slider. **Replay** runs the loaded frames again. The method line stays visible and says the runout is illustrative, not a forecast of timing. There is no snowpack in the model, so this is not an avalanche. Callouts name rangers or a public notice, and every public notice says it is a draft that was not sent.

The page has no rain section and no reasoning side panel: the Weather card's trace carries the rain, and each card's trace is the reasoning. The hiker card is not on this page for now.

On Mount Rainier the trail scores come from the saved heat map and the traces and measures from a live run. The scripted traces on static mountains are illustrative.

The wordmark returns to the globe. The mountain panel does not reopen by itself.

### Hill page

One page, `/hills/[slug]`, for Turtle Mountain. It uses the mountain page's split: 3D terrain on the left, the same panel on the right. Prevention shows the 72-hour card and, when trails exist, the trail list. With no trails it says "No trails are mapped here." and does not show **Simulate**.

Response shows the five agent cards idle. **Analyze now** is absent. Nothing on this page starts a run.

The hover card on the globe adds the line "Hill. Landslide model." beside the name, elevation, region, and risk badge the mountain markers already use.

## What would make the UX wrong

- A third audience (search and rescue, insurance, event organizers) gets its own screen.
- The hiker card shows drivers, weights, or AUC.
- The ranger panel hides the mile range.
- Layer toggles grow past probability, susceptibility, and historical pins, or appear in the mountain panel.
- The globe gains a dashboard of live counters before the three markers and the fly-to feel finished.
- A reasoning trace opens on its own, more than one is open at once, or a trace grows controls that change a run.
- The mountain page grows a second sidebar, a drawer, or a rain section.
- The simulation grows a rain slider, a speed control, a hazard picker, a scrubber, or any other what-if input. The time bar on the mountain view only shows the span.
- A callout reads as if a message was sent, or a public notice has a send button.
- The simulation shows a timing or a flow path as a prediction.
- The mountain panel shows agent cards or **Analyze now**. Those live on the mountain page.
- The hill page runs the agents, or **Analyze now** appears there.
- The hill glyph uses a new color. Risk color is the only difference between a safe hill and a dangerous one.

## How to check a UI change

Run the frontend and walk the demo order: land on the globe, open Mount Rainier, press **Simulate** and watch the flow and the time bar stay in step through the end, press **View** on each of the five trails and hover each marker, toggle a layer, press **Analyze now**, open each agent's trace, and read the reactive measures. Open a peak with no routes and confirm **Simulate** is absent. A still screenshot of one screen is not the check. Confirm the click path and the empty, loading, and error states for the view you touched.
