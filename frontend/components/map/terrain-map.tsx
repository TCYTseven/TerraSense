"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import {
  type GeoJSONSource,
  type MapLayerMouseEvent,
  MapLibreMap,
  type MapMouseEvent,
  type MapSourceDataEvent,
  Marker,
  NavigationControl,
  Popup,
  type RasterTileSource,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { formatDate, hazardLabel, humanize, riskLabel } from "@/lib/format";
import { RISK_COLORS, THEME } from "@/lib/theme";
import type { Hazard, HistoricalEvent, LayerTiles, Position, Trail } from "@/lib/types";
import LayerToggles from "./layer-toggles";
import {
  CAMERA,
  HAZARD_OUTLINE_COLOR,
  hazardFeatures,
  HEAT_FADE_MS,
  HISTORY_LAYER,
  historyFeatures,
  LAYER,
  mountainStyle,
  openingBounds,
  rasterSource,
  SOURCE,
  trailFeatures,
} from "./map-style";

// Copied from node_modules by scripts/copy-maplibre-worker.mjs on npm install.
const WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

const CATALOG_ATTRIBUTION = "NASA Global Landslide Catalog";

type MapStatus = "loading" | "ready" | "no-webgl" | "error";

const STATUS_TEXT: Record<Exclude<MapStatus, "ready">, string> = {
  loading: "Loading terrain…",
  "no-webgl": "The map needs WebGL, which this browser has turned off.",
  error: "The map could not load. Reload the page to try again.",
};

export interface TerrainMapProps {
  name: string;
  lon: number;
  lat: number;
  /** Summit elevation. The relief tint turns white toward it. */
  elevationM: number;
  trails: Trail[];
  /** Static mountains show terrain and trails only: no raster layers and no toggles. */
  isLive: boolean;
  /** The 72-hour probability tiles: the default layer. Null before the first scoring. */
  probability: LayerTiles | null;
  /** The susceptibility tiles, or null when the layer is not rendered. */
  susceptibility: LayerTiles | null;
  /** The latest hazard, outlined on the map, with its pin. */
  hazard: Hazard | null;
  /** The pin is selected: the panel shows the hazard. */
  hazardSelected: boolean;
  onHazardClick: () => void;
  /** A click on the map that hits no pin. */
  onMapClick: () => void;
  /** Past landslides for the pins. Empty until the catalog is downloaded. */
  historicalEvents: HistoricalEvent[];
}

/** A small label pinned to the summit. MapLibre lifts it onto the 3D terrain. */
function summitLabel(name: string): HTMLElement {
  const label = document.createElement("div");
  label.className =
    "pointer-events-none flex items-center gap-1.5 rounded-full bg-popover px-2.5 py-1 text-xs font-medium text-popover-foreground ring-1 ring-border";
  const peak = document.createElement("span");
  peak.setAttribute("aria-hidden", "true");
  peak.className = "text-[0.6rem] text-muted-foreground";
  peak.textContent = "▲";
  const text = document.createElement("span");
  text.textContent = name;
  label.append(peak, text);
  return label;
}

/**
 * The popup for a historical pin: date, type, and source. Catalog text is external data,
 * so it goes in as text, never as HTML.
 */
function historyPopup(properties: Record<string, unknown>): HTMLElement {
  const text = (key: string) => (typeof properties[key] === "string" ? (properties[key] as string) : null);
  const root = document.createElement("div");
  root.className = "space-y-0.5 text-xs";

  const date = document.createElement("p");
  date.className = "font-medium";
  const day = text("date");
  date.textContent = day ? formatDate(day) : "Date unknown";

  const kind = document.createElement("p");
  const category = text("category");
  kind.textContent = category ? humanize(category) : "Landslide";

  const source = document.createElement("p");
  source.className = "text-muted-foreground";
  const label = text("source_name") ?? text("catalog") ?? CATALOG_ATTRIBUTION;
  const link = text("source_link");
  if (link && /^https?:\/\//i.test(link)) {
    const anchor = document.createElement("a");
    anchor.href = link;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.className = "text-primary underline decoration-1 underline-offset-3";
    anchor.textContent = label;
    source.append(anchor);
  } else {
    source.textContent = label;
  }

  root.append(date, kind, source);
  return root;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** How long a heat map fade waits for its tiles before fading in anyway. */
const FADE_WAIT_MS = 3000;

/**
 * Redraw the layers draped on the 3D terrain. MapLibre caches them as textures keyed on the
 * tiles, the zoom, and which layers are visible, not on paint, so an opacity change would not
 * show until the camera moved. releaseAllRTT is not in MapLibre's public types: if a future
 * version drops it, the heat map still appears, just without the fade.
 */
function redrape(map: MapLibreMap) {
  const terrain = map.terrain as unknown as { tileManager?: { releaseAllRTT?: () => void } } | null;
  terrain?.tileManager?.releaseAllRTT?.();
  map.triggerRepaint();
}

/**
 * Hide a raster layer, then fade it in once its source's tiles in view have loaded: the heat
 * map's one motion. Instant under reduced motion. Returns a cancel function for effect cleanup.
 */
function fadeIn(map: MapLibreMap, layer: string, source: string): () => void {
  map.setPaintProperty(layer, "raster-opacity-transition", { duration: 0, delay: 0 });
  map.setPaintProperty(layer, "raster-opacity", 0);
  redrape(map);
  let done = false;
  let frame = 0;
  let settleTimer = 0;
  // The map goes idle only once the fade's transition has finished, so one last redraw then
  // leaves every tile at full opacity, even when slow frames stretch the fade.
  const settle = () => redrape(map);
  const show = () => {
    if (done || !map.getLayer(layer)) {
      return;
    }
    done = true;
    map.off("sourcedata", onData);
    window.clearTimeout(timer);
    const duration = prefersReducedMotion() ? 0 : HEAT_FADE_MS;
    map.setPaintProperty(layer, "raster-opacity-transition", { duration, delay: 0 });
    map.setPaintProperty(layer, "raster-opacity", 1);
    // Redraw the draped textures every frame of the fade, then once the map settles.
    const end = performance.now() + duration;
    const step = () => {
      redrape(map);
      if (performance.now() < end) {
        frame = window.requestAnimationFrame(step);
      }
    };
    step();
    map.once("idle", settle);
    settleTimer = window.setTimeout(settle, duration + FADE_WAIT_MS);
  };
  const onData = (event: MapSourceDataEvent) => {
    if (event.sourceId === source && map.isSourceLoaded(source)) {
      show();
    }
  };
  map.on("sourcedata", onData);
  // Tiles that never finish (a slow or failed tile server) still let the layer show.
  const timer = window.setTimeout(show, FADE_WAIT_MS);
  return () => {
    done = true;
    map.off("sourcedata", onData);
    map.off("idle", settle);
    window.clearTimeout(timer);
    window.clearTimeout(settleTimer);
    window.cancelAnimationFrame(frame);
  };
}

/** A point inside the zone for the pin: the centroid, or the grid point inside nearest to it. */
function pinPoint(ring: Position[]): Position {
  let area = 0;
  let x = 0;
  let y = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x0, y0] = ring[i];
    const [x1, y1] = ring[i + 1];
    const cross = x0 * y1 - x1 * y0;
    area += cross;
    x += (x0 + x1) * cross;
    y += (y0 + y1) * cross;
  }
  const centroid: Position = area ? [x / (3 * area), y / (3 * area)] : ring[0];
  if (inside(centroid, ring)) {
    return centroid;
  }
  const xs = ring.map((p) => p[0]);
  const ys = ring.map((p) => p[1]);
  const [west, east, south, north] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  let best: Position = ring[0];
  let bestDistance = Infinity;
  for (let i = 1; i < 24; i += 1) {
    for (let j = 1; j < 24; j += 1) {
      const candidate: Position = [west + ((east - west) * i) / 24, south + ((north - south) * j) / 24];
      const distance = (candidate[0] - centroid[0]) ** 2 + (candidate[1] - centroid[1]) ** 2;
      if (distance < bestDistance && inside(candidate, ring)) {
        best = candidate;
        bestDistance = distance;
      }
    }
  }
  return best;
}

/** Ray casting: is a point inside a polygon ring? */
function inside([px, py]: Position, ring: Position[]): boolean {
  let result = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      result = !result;
    }
  }
  return result;
}

/**
 * The hazard pin (design addendum, Trails, bypass, and pins): a 28 px circle in its level color
 * with a 2 px dark ring and a warning triangle. Selected, an accent ring sits outside the dark
 * ring, with a thin dark edge so it reads over snow. A button, so the keyboard reaches it.
 */
function stylePin(button: HTMLButtonElement, hazard: Hazard, selected: boolean) {
  button.style.background = RISK_COLORS[hazard.severity];
  button.style.boxShadow = selected
    ? `0 0 0 2px ${THEME.background}, 0 0 0 4px ${THEME.primary}, 0 0 0 5px ${THEME.background}`
    : `0 0 0 2px ${THEME.background}`;
  button.setAttribute("aria-pressed", String(selected));
  button.setAttribute(
    "aria-label",
    `${hazardLabel(hazard.type)} hazard, ${riskLabel(hazard.severity)}. ${selected ? "Hide" : "Show"} its details.`,
  );
}

function pinElement(): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "grid size-7 cursor-pointer place-items-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-4";
  button.innerHTML =
    `<svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="${THEME.background}" ` +
    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>' +
    '<path d="M12 9v4M12 17h.01"/></svg>';
  return button;
}

function hasWebGL(): boolean {
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

/**
 * The mountain map: 3D terrain, a light shaded relief (or satellite with a Mapbox token),
 * the trails, and for live mountains the susceptibility layer and past landslide pins.
 * Browser-only. Load it through ./mountain-map.tsx.
 */
export default function TerrainMap({
  name,
  lon,
  lat,
  elevationM,
  trails,
  isLive,
  probability,
  susceptibility,
  hazard,
  hazardSelected,
  onHazardClick,
  onMapClick,
  historicalEvents,
}: TerrainMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [webgl] = useState(hasWebGL);
  const [status, setStatus] = useState<MapStatus>(webgl ? "loading" : "no-webgl");
  const [showSusceptibility, setShowSusceptibility] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  // The camera frames the trails the page opened with. Later updates only restyle the lines.
  const trailsAtOpen = useRef(trails);
  // The latest callbacks, so listeners registered once always call the current ones.
  const hazardClick = useRef(onHazardClick);
  const mapClick = useRef(onMapClick);
  const pin = useRef<{ marker: Marker; button: HTMLButtonElement } | null>(null);
  useEffect(() => {
    hazardClick.current = onHazardClick;
    mapClick.current = onMapClick;
  });

  useEffect(() => {
    if (!container.current || !webgl) {
      return;
    }
    setWorkerUrl(WORKER_URL);
    // Open on the summit and the hero trail together, or on the summit alone.
    const bounds = openingBounds(lon, lat, trailsAtOpen.current);
    const instance = new MapLibreMap({
      container: container.current,
      style: mountainStyle({ summitM: elevationM, mapboxToken: process.env.NEXT_PUBLIC_MAPBOX_TOKEN || undefined }),
      center: [lon, lat],
      zoom: CAMERA.zoom,
      pitch: CAMERA.pitch,
      bearing: CAMERA.bearing,
      maxPitch: CAMERA.maxPitch,
      ...(bounds && {
        bounds,
        fitBoundsOptions: { padding: CAMERA.padding, pitch: CAMERA.pitch, bearing: CAMERA.bearing },
      }),
      attributionControl: { compact: true },
    });
    instance.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
    instance.addControl(new ScaleControl({ unit: "imperial" }), "bottom-right");
    new Marker({ element: summitLabel(name), anchor: "bottom", offset: [0, -4] }).setLngLat([lon, lat]).addTo(instance);
    instance.once("load", () => {
      setMap(instance);
      setStatus("ready");
    });
    instance.on("error", (event) => {
      // A tile that fails to load is not fatal: the map fills in around it.
      if ("sourceId" in event || "tile" in event) {
        return;
      }
      setStatus((current) => (current === "ready" ? current : "error"));
    });
    return () => instance.remove();
  }, [name, lon, lat, elevationM, webgl]);

  useEffect(() => {
    map?.getSource<GeoJSONSource>(SOURCE.trails)?.setData(trailFeatures(trails));
  }, [map, trails]);

  // Susceptibility sits under the trails. It appears at once: no fade on toggle or tile load.
  useEffect(() => {
    if (!map || !susceptibility) {
      return;
    }
    const source = map.getSource<RasterTileSource>(SOURCE.susceptibility);
    if (source) {
      source.setTiles([susceptibility.tiles]);
      return;
    }
    map.addSource(SOURCE.susceptibility, rasterSource(susceptibility));
    map.addLayer(
      {
        id: LAYER.susceptibility,
        type: "raster",
        source: SOURCE.susceptibility,
        layout: { visibility: "none" },
        paint: { "raster-fade-duration": 0 },
      },
      LAYER.otherTrails,
    );
  }, [map, susceptibility]);

  useEffect(() => {
    if (map?.getLayer(LAYER.susceptibility)) {
      map.setLayoutProperty(LAYER.susceptibility, "visibility", showSusceptibility ? "visible" : "none");
    }
  }, [map, susceptibility, showSusceptibility]);

  // The 72-hour heat map: the page's default layer, under the trails. It fades in when it first
  // shows and again when a finished run brings new tiles.
  useEffect(() => {
    if (!map || !probability) {
      return;
    }
    const source = map.getSource<RasterTileSource>(SOURCE.probability);
    if (source) {
      source.setTiles([probability.tiles]);
    } else {
      map.addSource(SOURCE.probability, rasterSource(probability));
      map.addLayer(
        {
          id: LAYER.probability,
          type: "raster",
          source: SOURCE.probability,
          paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
        },
        LAYER.otherTrails,
      );
    }
    return fadeIn(map, LAYER.probability, SOURCE.probability);
  }, [map, probability]);

  // One raster at a time: susceptibility hides the heat map while it is on.
  useEffect(() => {
    if (map?.getLayer(LAYER.probability)) {
      map.setLayoutProperty(LAYER.probability, "visibility", showSusceptibility ? "none" : "visible");
    }
  }, [map, probability, showSusceptibility]);

  // The hazard zone's outline, under the trails so the trail colors stay readable across it.
  useEffect(() => {
    if (!map || !isLive) {
      return;
    }
    const data = hazardFeatures(hazard);
    const source = map.getSource<GeoJSONSource>(SOURCE.hazard);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(SOURCE.hazard, { type: "geojson", data });
    map.addLayer(
      {
        id: LAYER.hazardOutline,
        type: "line",
        source: SOURCE.hazard,
        layout: { "line-join": "round" },
        paint: { "line-color": HAZARD_OUTLINE_COLOR, "line-width": 2 },
      },
      LAYER.otherTrails,
    );
  }, [map, isLive, hazard]);

  // The hazard pin, on a point inside the zone.
  useEffect(() => {
    if (!map || !isLive || !hazard) {
      pin.current?.marker.remove();
      pin.current = null;
      return;
    }
    if (!pin.current) {
      const button = pinElement();
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        hazardClick.current();
      });
      pin.current = { button, marker: new Marker({ element: button, anchor: "center" }) };
    }
    stylePin(pin.current.button, hazard, hazardSelected);
    pin.current.marker.setLngLat(pinPoint(hazard.geom.coordinates[0])).addTo(map);
  }, [map, isLive, hazard, hazardSelected]);

  useEffect(
    () => () => {
      pin.current?.marker.remove();
    },
    [],
  );

  // A click on the empty map closes the hazard. Historical pins handle their own clicks.
  useEffect(() => {
    if (!map) {
      return;
    }
    const onClick = (event: MapMouseEvent) => {
      const onPin = map.getLayer(LAYER.history) && map.queryRenderedFeatures(event.point, { layers: [LAYER.history] }).length;
      if (!onPin) {
        mapClick.current();
      }
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
    };
  }, [map]);

  // Past landslide pins sit above the trails.
  useEffect(() => {
    if (!map || !isLive) {
      return;
    }
    const data = historyFeatures(historicalEvents);
    const source = map.getSource<GeoJSONSource>(SOURCE.history);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(SOURCE.history, { type: "geojson", data, attribution: CATALOG_ATTRIBUTION });
    map.addLayer({ ...HISTORY_LAYER, layout: { visibility: "none" } });
  }, [map, isLive, historicalEvents]);

  useEffect(() => {
    if (map?.getLayer(LAYER.history)) {
      map.setLayoutProperty(LAYER.history, "visibility", showHistory ? "visible" : "none");
    }
  }, [map, historicalEvents, showHistory]);

  // A pin click opens its popup. A click anywhere else on the map closes it.
  useEffect(() => {
    if (!map || !isLive) {
      return;
    }
    const open = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature || feature.geometry.type !== "Point") {
        return;
      }
      const [pinLon, pinLat] = feature.geometry.coordinates;
      new Popup({ closeButton: false, className: "terra-popup", offset: 10, maxWidth: "260px" })
        .setLngLat([pinLon, pinLat])
        .setDOMContent(historyPopup(feature.properties))
        .addTo(map);
    };
    const pointer = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const reset = () => {
      map.getCanvas().style.cursor = "";
    };
    map.on("click", LAYER.history, open);
    map.on("mouseenter", LAYER.history, pointer);
    map.on("mouseleave", LAYER.history, reset);
    return () => {
      map.off("click", LAYER.history, open);
      map.off("mouseenter", LAYER.history, pointer);
      map.off("mouseleave", LAYER.history, reset);
    };
  }, [map, isLive]);

  function toggle(id: string) {
    if (id === LAYER.susceptibility) {
      setShowSusceptibility((on) => !on);
    } else if (id === LAYER.history) {
      setShowHistory((on) => !on);
    }
  }

  return (
    <div className="absolute inset-0">
      {/* MapLibre's stylesheet sets the container to position: relative, so size it by height. */}
      <div ref={container} className="h-full w-full" />
      {isLive && status === "ready" && (
        <LayerToggles
          toggles={[
            {
              id: LAYER.susceptibility,
              label: "Susceptibility",
              on: showSusceptibility,
              unavailable: susceptibility ? undefined : "The susceptibility layer is not rendered yet.",
            },
            {
              id: LAYER.history,
              label: "Past landslides",
              on: showHistory,
              unavailable:
                historicalEvents.length > 0 ? undefined : "No catalog landslides in the Rainier box yet.",
            },
          ]}
          onToggle={toggle}
        />
      )}
      {status !== "ready" && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <p className="rounded-lg border border-border bg-popover px-3 py-2 text-sm text-muted-foreground">{STATUS_TEXT[status]}</p>
        </div>
      )}
    </div>
  );
}
