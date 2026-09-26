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

The judge demo walks that order on purpose: globe, mountain panel, simulation, mountain page, agents, reasoning, hiker card. Each surface has one job. A control that serves a third audience does not ship this weekend.

## Rules

1. **Risk colors mean risk.** Green, amber, orange, and red appear only on markers, trails, heat, the simulated flow, and severity. The accent cyan is the only interactive color.
2. **The globe stays almost empty until a click.** Name, search, globe. Stats, legends, and settings do not go on this screen. A click on a marker opens the mountain panel over it, and closing the panel returns the empty globe.
3. **The mountain page is a map plus one panel.** The map is about 70% of the width. Layer toggles sit on the map. Actions live in the panel: **Analyze now** and **Hiker forecast**.
4. **A hazard explains itself in four lines, in this order.** What it is. Why it was flagged. Confidence. How to avoid it.
5. **Ranger copy is short.** Name the hazard, the place, and the confidence. Skip a lecture.
6. **Hiker copy is one sentence plus the bypass.** Name the bypass, the added distance, and the added climb. Skip probability jargon.
7. **Weather is text in a panel.** Past rain and the next day. It is not a map layer.
8. **Static mountains do not pretend to analyze.** Hide **Analyze now**, the pressure points, and **Simulate** when `is_live` is false.
9. **A running analysis is visible.** Five rows, each waiting, running, or done. The running row moves. A failure says the run failed and leaves the last good hazard on the map.
10. **Motion is short.** Idle globe spin. Fly-to in about 1.5 seconds. Heat map fades in. A simulation plays its flow down the slope. Nothing else animates unless it shows that work is happening.
11. **A simulation says what it is.** It is an illustrative runout from today's worst slope, not a forecast of timing. Every public message it shows is a draft that was not sent.

## The screens

### Globe

Full viewport. Dark earth, three markers colored by risk, slow idle rotation, hover card (name, risk, last refresh), and search.

A marker click or a search pick turns the globe to face the mountain, then opens the mountain panel in the center of the screen. The spin pauses while the panel is open.

### Mountain panel (team decision, Sep 25, 2026)

One panel, centered over the globe, for every mountain. It closes with Escape, its close button, or a click on the globe around it.

**Left: the mountain.** A 3D terrain map of the mountain with the 72-hour heat map and numbered pins on the pressure points. Trails are drawn and the hero trail is colored by segment. The map has no toggles.

**Right: the pressure points.** The mountain's name and overall level, then up to five pressure points: the slopes most likely to fail, worst first. Each row gives its number, where it is, its level, and the terrain that drives it. A click on a row selects it and its pin, and that point is the one the simulation starts from. The first point is selected when the panel opens.

**Bottom of the right side:** **Simulate**, the primary action, and **Open ranger view**, which flies into the mountain page.

**After Simulate, the right side becomes the simulation.** The left map plays the flow down the slope from the selected pressure point. The heat of the flow advances step by step, and each place it reaches a trail gets marked. The right side shows:

- **Steps.** The simulation's steps in order, each with its simulated time: release, entering the channel, each trail it reaches (trail and mile range), and where it stops. The current step is marked the way a running agent row is.
- **Callouts.** Two to four short notes from the AI, each tied to a step and each naming who it is for:
  - **Rangers:** what to do now, such as closing a mile range or sending a patrol to a trailhead.
  - **Public notice:** the message that would go out to people nearby, shown as a draft that was not sent.

The simulation has no speed control, scrubber, or rain slider. **Replay** runs it again. **Back to pressure points** restores the right side. The left map keeps the final flow until one of those is pressed.

Static mountains open the same panel with terrain only, their fixed level, and one line saying they are display markers. No pressure points, no **Simulate**.

### Mountain page

3D terrain on a light shaded relief, or Mapbox satellite when a token is set. Default layer is the 72-hour probability heat map. Toggles: susceptibility, historical pins. Trails colored by segment. One hazard pin.

Panel contents, top to bottom: mountain name and elevation, overall risk and one sentence, rain totals, trail list, agent rows, **Analyze now**, **Hiker forecast**.

The hiker card replaces the dense panel content with larger type. It draws the bypass on the same map. It does not navigate to a separate marketing page.

The wordmark returns to the globe. The mountain panel does not reopen by itself.

### Reasoning panel (team decision, Sep 25, 2026)

**Reasoning** in the Agents section, or a click on any agent row, opens a side panel over the map, beside the ranger panel. For each agent it shows which model the router picked (Gemini Flash or Grok) and why, rule by rule; the facts the agent's tools returned; the model's own thinking summary and the steps it gave; what the code changed afterwards; and every call it took, fallbacks included. It updates live during a run and closes with Escape. It serves the same ranger: it answers "why should I trust this alert?" It is not a third audience's screen.

## What would make the UX wrong

- A third audience (search and rescue, insurance, event organizers) gets its own screen.
- The hiker card shows drivers, weights, or AUC.
- The ranger panel hides the mile range.
- Layer toggles grow past probability, susceptibility, and historical pins, or appear in the mountain panel.
- The globe gains a dashboard of live counters before the three markers and the fly-to feel finished.
- The reasoning panel opens on its own, or grows controls that change a run.
- The simulation grows a rain slider, a speed control, a hazard picker, or any other what-if input.
- A callout reads as if a message was sent, or a public notice has a send button.
- The simulation shows a timing or a flow path as a prediction.
- The mountain panel shows agent rows, **Analyze now**, or the hiker card. Those live on the mountain page.

## How to check a UI change

Run the frontend and walk the demo order: land on the globe, click Rainier, read the pressure points, press **Simulate** and watch it to the end, open the ranger view, toggle a layer, open the pin, start analyze, open the hiker card. A still screenshot of one screen is not the check. Confirm the click path and the empty, loading, and error states for the view you touched.
