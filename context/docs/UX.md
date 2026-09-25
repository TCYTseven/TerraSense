# UX

Why TerraSense has two surfaces, and the rules for adding anything to either one.

The visual tokens (colors, type, motion) are in [`../TerraSense.md`](../TerraSense.md) under Design Language. This file decides whether a control belongs on screen. When they disagree about a color, the spec wins. When they disagree about whether to add a control, this file wins.

## The problem

A ranger and a hiker need different sentences from the same model.

The ranger is at a desk or in a truck after a storm, deciding whether to close a segment. They can read a panel. They need the trail, the miles, the severity, and why.

The hiker is about to leave, often on a phone, often in a group chat. They need one level and one action: go, or take the other trail.

A heat map alone serves neither person. A paragraph of model features serves neither person. The screen has to end in a label someone can act on.

## The thesis

**The globe is the way in. The mountain page is a dispatch board for the ranger. The hiker card is the only place that reads like a consumer app.**

The judge demo walks that order on purpose: globe, mountain, agents, Discord, hiker card. Each surface has one job. A control that serves a third job does not ship this weekend.

## Rules

1. **Risk colors mean risk.** Green, amber, orange, and red appear only on markers, trails, heat, and severity. The accent cyan is the only interactive color.
2. **The globe stays almost empty.** Name, search, globe. Stats, legends, and settings do not go on this screen.
3. **The mountain page is a map plus one panel.** The map is about 70% of the width. Layer toggles sit on the map. Actions live in the panel: **Analyze now** and **Hiker forecast**.
4. **A hazard explains itself in four lines, in this order.** What it is. Why it was flagged. Confidence. How to avoid it.
5. **Ranger copy is short.** Name the hazard, the place, and the confidence. Skip a lecture.
6. **Hiker copy is one sentence plus the bypass.** Name the bypass, the added distance, and the added climb. Skip probability jargon.
7. **Weather is text in the panel.** Past rain and the next day. It is not a map layer.
8. **Static mountains do not pretend to analyze.** Hide **Analyze now** when `is_live` is false.
9. **A running analysis is visible.** Five rows, each waiting, running, or done. The running row moves. A failure says the run failed and leaves the last good hazard on the map.
10. **Motion is short.** Idle globe spin. Fly-to in about 1.5 seconds. Heat map fades in. Nothing else animates unless it shows that work is happening.

## The two screens

### Globe

Full viewport. Dark earth, three markers colored by risk, slow idle rotation, hover card (name, risk, last refresh), search that flies to a mountain, click that flies in and then opens the mountain page.

The camera move and the route change are one gesture. The page does not cut.

### Mountain

3D terrain on a light shaded relief, or Mapbox satellite when a token is set. Default layer is the 72-hour probability heat map. Toggles: susceptibility, historical pins. Trails colored by segment. One hazard pin.

Panel contents, top to bottom: mountain name and elevation, overall risk and one sentence, rain totals, trail list, agent rows, **Analyze now**, **Hiker forecast**.

The hiker card replaces the dense panel content with larger type. It draws the bypass on the same map. It does not navigate to a separate marketing page.

## What would make the UX wrong

- A third audience (search and rescue, insurance, event organizers) gets its own screen.
- The hiker card shows drivers, weights, or AUC.
- The ranger panel hides the mile range.
- Layer toggles grow past probability, susceptibility, and historical pins.
- The globe gains a dashboard of live counters before the three markers and the fly-to feel finished.

## How to check a UI change

Run the frontend and walk the demo order: land on the globe, search Rainier, land on the mountain, toggle a layer, open the pin, start analyze, open the hiker card. A still screenshot of one screen is not the check. Confirm the click path and the empty, loading, and error states for the view you touched.
