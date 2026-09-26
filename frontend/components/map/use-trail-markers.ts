"use client";

import { type GeoJSONSource, type MapLibreMap, type MapMouseEvent, Marker, Popup } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { formatScore, riskLabel } from "@/lib/format";
import type { CameraFocus, TrailLetter, TrailRisk } from "@/lib/hill";
import { RISK_COLORS, THEME } from "@/lib/theme";
import { HAZARD_OUTLINE_COLOR, LAYER, SOURCE, trailRiskFeatures, trailRiskPaint } from "./map-style";

/** Hovering the ground this close to a trail's center shows its tooltip, in meters. */
const REGION_RADIUS_M = 400;
/** The camera's tilt when it flies to a trail. */
const FOCUS_PITCH = 60;
/** The one fly-to: 1.5 s. */
const FLY_MS = 1500;
/** A marker behind a ridge stays readable. The selected one never fades. */
const COVERED_OPACITY = "0.6";

const METERS_PER_DEG_LAT = 110_540;
const METERS_PER_DEG_LON_AT_EQUATOR = 111_320;

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function metersBetween([lon0, lat0]: [number, number], [lon1, lat1]: [number, number]): number {
  const dx = (lon1 - lon0) * METERS_PER_DEG_LON_AT_EQUATOR * Math.cos(((lat0 + lat1) / 2) * (Math.PI / 180));
  const dy = (lat1 - lat0) * METERS_PER_DEG_LAT;
  return Math.hypot(dx, dy);
}

/** "Trail A, Kautz Creek Trail, risk 0.74". */
export function trailAriaLabel(trail: TrailRisk): string {
  return `Trail ${trail.letter}, ${trail.name}, risk ${formatScore(trail.score)}`;
}

/**
 * A trail's letter badge: a 24 px circle in its level color with the letter in dark text and a
 * 1 px dark ring so it reads on light relief. Selected, a cyan ring sits outside the dark one.
 */
function styleBadge(button: HTMLButtonElement, trail: TrailRisk, selected: boolean) {
  button.style.background = RISK_COLORS[trail.level];
  button.style.color = THEME.background;
  button.style.boxShadow = selected
    ? `0 0 0 1px ${THEME.background}, 0 0 0 3px ${THEME.primary}, 0 0 0 4px ${THEME.background}`
    : `0 0 0 1px ${THEME.background}`;
  button.setAttribute("aria-pressed", String(selected));
}

function badgeElement(trail: TrailRisk): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className =
    "grid size-6 cursor-pointer place-items-center rounded-full text-xs leading-none font-semibold focus-visible:outline-2 focus-visible:outline-offset-4";
  button.setAttribute("aria-label", trailAriaLabel(trail));
  button.textContent = trail.letter;
  return button;
}

/** The tooltip: name, score and level, slope, and the primary factor. Text nodes only. */
function tooltipContent(trail: TrailRisk): HTMLElement {
  const root = document.createElement("div");
  root.className = "space-y-1 text-xs";

  const name = document.createElement("p");
  name.className = "font-medium text-sm";
  name.textContent = trail.name;

  const row = (label: string, value: string, mono: boolean, suffix?: string) => {
    const line = document.createElement("p");
    line.className = "flex items-baseline justify-between gap-4";
    const key = document.createElement("span");
    key.className = "text-muted-foreground";
    key.textContent = label;
    const val = document.createElement("span");
    const number = document.createElement("span");
    if (mono) {
      number.className = "font-mono tabular-nums";
    }
    number.textContent = value;
    val.append(number);
    if (suffix) {
      val.append(document.createTextNode(` ${suffix}`));
    }
    line.append(key, val);
    return line;
  };

  root.append(
    name,
    row("Risk", formatScore(trail.score), true, riskLabel(trail.level)),
    row("Slope", `${Math.round(trail.slopeDeg)}°`, true),
    row("Primary factor", trail.primaryFactor, false),
  );
  return root;
}

/** Everything the markers need, rebuilt when the trails change. */
interface Controller {
  buttons: Map<TrailLetter, HTMLButtonElement>;
  markers: Map<TrailLetter, Marker>;
  /** Show a trail's tooltip until the pointer moves off, the map is clicked, or the camera moves by hand. */
  pin: (letter: TrailLetter | null) => void;
}

/** A string that changes only when what the markers draw changes, so a new array alone does not rebuild them. */
function signatureOf(trails: TrailRisk[]): string {
  return trails
    .map((t) =>
      [t.letter, t.name, t.score, t.level, t.slopeDeg, t.primaryFactor, t.center.join(","), t.zoom, t.geom?.coordinates.length ?? 0].join("|"),
    )
    .join(";");
}

/**
 * The lettered trail markers (A to E) on the mountain map: one Marker each at the trail's
 * center, a hover and focus tooltip, a subtle line for trails that have one, and a fly-to
 * whenever `focus` brings a new nonce. All imperative: no React state, so nothing re-renders.
 */
export function useTrailMarkers(map: MapLibreMap | null, trails: TrailRisk[], focus: CameraFocus | null) {
  const trailsRef = useRef(trails);
  const controller = useRef<Controller | null>(null);
  const signature = signatureOf(trails);
  const selected = focus?.letter ?? null;

  useEffect(() => {
    trailsRef.current = trails;
  });

  // Build the markers, the tooltip, and the lines. Rebuilt when the trails change.
  useEffect(() => {
    const current = trailsRef.current;
    if (!map || current.length === 0) {
      return;
    }
    const byLetter = new Map(current.map((trail) => [trail.letter, trail]));
    const popup = new Popup({
      closeButton: false,
      closeOnClick: false,
      className: "terra-popup",
      offset: 18,
      maxWidth: "260px",
    });

    // Who wants a tooltip, strongest first: the pointer on a marker, keyboard focus,
    // the pointer over a trail's region, then the trail the camera just flew to.
    let markerHover: TrailLetter | null = null;
    let keyboard: TrailLetter | null = null;
    let region: TrailLetter | null = null;
    let pinned: TrailLetter | null = null;
    let shown: TrailLetter | null = null;
    const render = () => {
      const next = markerHover ?? keyboard ?? region ?? pinned;
      if (next === shown) {
        return;
      }
      shown = next;
      const trail = next ? byLetter.get(next) : undefined;
      if (!trail) {
        popup.remove();
        return;
      }
      popup.setLngLat(trail.center).setDOMContent(tooltipContent(trail));
      if (!popup.isOpen()) {
        popup.addTo(map);
      }
    };

    const buttons = new Map<TrailLetter, HTMLButtonElement>();
    const markers = new Map<TrailLetter, Marker>();
    for (const trail of current) {
      const button = badgeElement(trail);
      styleBadge(button, trail, false);
      button.addEventListener("mouseenter", () => {
        markerHover = trail.letter;
        render();
      });
      button.addEventListener("mouseleave", () => {
        markerHover = null;
        render();
      });
      button.addEventListener("focus", () => {
        keyboard = trail.letter;
        render();
      });
      button.addEventListener("blur", () => {
        keyboard = null;
        render();
      });
      // A tap (no hover on touch) keeps the tooltip up.
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        pinned = trail.letter;
        render();
      });
      buttons.set(trail.letter, button);
      markers.set(
        trail.letter,
        new Marker({ element: button, anchor: "center", opacityWhenCovered: COVERED_OPACITY }).setLngLat(trail.center).addTo(map),
      );
    }

    const onMove = (event: MapMouseEvent) => {
      const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];
      let nearest: TrailLetter | null = null;
      let best = REGION_RADIUS_M;
      for (const trail of current) {
        const distance = metersBetween(point, trail.center);
        if (distance <= best) {
          best = distance;
          nearest = trail.letter;
        }
      }
      if (nearest !== region) {
        region = nearest;
        render();
      }
    };
    const onOut = () => {
      region = null;
      render();
    };
    const onClick = (event: MapMouseEvent) => {
      const target = event.originalEvent.target;
      if (target instanceof Node && [...buttons.values()].some((button) => button.contains(target))) {
        return;
      }
      pinned = null;
      render();
    };
    // A drag, scroll, or rotate by hand lets go of the flown-to trail's tooltip.
    const onUserMove = (event: { originalEvent?: Event }) => {
      if (event.originalEvent) {
        pinned = null;
        render();
      }
    };
    map.on("mousemove", onMove);
    map.on("mouseout", onOut);
    map.on("click", onClick);
    map.on("movestart", onUserMove);

    // The lines, above the dashed context trails and under the hero trail.
    const data = trailRiskFeatures(current);
    const source = map.getSource<GeoJSONSource>(SOURCE.trailRisk);
    if (source) {
      source.setData(data);
    } else {
      map.addSource(SOURCE.trailRisk, { type: "geojson", data });
      const paint = trailRiskPaint(null);
      map.addLayer(
        {
          id: LAYER.trailRisk,
          type: "line",
          source: SOURCE.trailRisk,
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": HAZARD_OUTLINE_COLOR, "line-width": paint.width, "line-opacity": paint.opacity },
        },
        map.getLayer(LAYER.heroCasing) ? LAYER.heroCasing : undefined,
      );
    }

    controller.current = {
      buttons,
      markers,
      pin: (letter) => {
        pinned = letter;
        render();
      },
    };

    return () => {
      controller.current = null;
      map.off("mousemove", onMove);
      map.off("mouseout", onOut);
      map.off("click", onClick);
      map.off("movestart", onUserMove);
      popup.remove();
      markers.forEach((marker) => marker.remove());
      // The map may already be gone when the page unmounts.
      try {
        map.getSource<GeoJSONSource>(SOURCE.trailRisk)?.setData(trailRiskFeatures([]));
      } catch {
        // Nothing left to clear.
      }
    };
  }, [map, signature]);

  // The selected letter: a cyan ring on its marker and a heavier line.
  useEffect(() => {
    const built = controller.current;
    if (!map || !built) {
      return;
    }
    for (const trail of trailsRef.current) {
      const button = built.buttons.get(trail.letter);
      if (button) {
        styleBadge(button, trail, trail.letter === selected);
      }
      built.markers.get(trail.letter)?.setOpacity("1", trail.letter === selected ? "1" : COVERED_OPACITY);
    }
    if (map.getLayer(LAYER.trailRisk)) {
      const paint = trailRiskPaint(selected);
      map.setPaintProperty(LAYER.trailRisk, "line-width", paint.width);
      map.setPaintProperty(LAYER.trailRisk, "line-opacity", paint.opacity);
    }
  }, [map, signature, selected]);

  // A new focus (a new nonce, even for the same letter) flies to that trail's region, then
  // shows its tooltip. Under reduced motion the camera jumps.
  useEffect(() => {
    if (!map || !focus) {
      return;
    }
    const trail = trailsRef.current.find((t) => t.letter === focus.letter);
    if (!trail) {
      return;
    }
    const tag = { trailFocus: focus.nonce };
    let arrived = false;
    // MapLibre merges the flight's event data into its moveend event.
    const onEnd = (event: object) => {
      if ((event as { trailFocus?: number }).trailFocus !== focus.nonce) {
        return;
      }
      arrived = true;
      map.off("moveend", onEnd);
      controller.current?.pin(trail.letter);
    };
    map.on("moveend", onEnd);
    controller.current?.pin(null);
    const camera = { center: trail.center, zoom: trail.zoom, pitch: FOCUS_PITCH, bearing: map.getBearing() };
    if (prefersReducedMotion()) {
      map.jumpTo(camera, tag);
    } else {
      map.flyTo({ ...camera, duration: FLY_MS }, tag);
    }
    return () => {
      if (!arrived) {
        map.off("moveend", onEnd);
      }
    };
  }, [map, focus]);
}
