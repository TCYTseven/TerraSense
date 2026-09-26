"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import {
  type GeoJSONSource,
  type ImageSource,
  type RasterTileSource,
  MapLibreMap,
  type MapMouseEvent,
  type MapSourceDataEvent,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { hazardLabel, riskLabel } from "@/lib/format";
import { FLOW_COLORS, RISK_COLORS, THEME } from "@/lib/theme";
import type { CameraFocus, TrailLetter, TrailRisk } from "@/lib/mountain-view";
import type { ReleaseCamera } from "@/lib/use-simulation";
import type { Bypass, FlowFeatureCollection, Hazard, HistoricalEvent, LayerTiles, Position, Trail } from "@/lib/types";
import { buildSyntheticHeatOverlay } from "@/lib/synthetic-heatmap";
import {
  bypassFeatures,
  CAMERA,
  DIMMED_TRAIL_OPACITY,
  HAZARD_OUTLINE_COLOR,
  hazardFeatures,
  HEAT_FADE_MS,
  LAYER,
  mountainStyle,
  openingBearing,
  heatDrapeBounds,
  openingBounds,
  openingZoomFloor,
  rasterSource,
  SOURCE,
  trailFeatures,
} from "./map-style";
import { useIdleOrbit } from "./use-idle-orbit";
import { useTrailMarkers } from "./use-trail-markers";

// Copied from node_modules by scripts/copy-maplibre-worker.mjs on npm install.
const WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

type MapStatus = "loading" | "ready" | "no-webgl" | "error";

const STATUS_TEXT: Record<Exclude<MapStatus, "ready">, string> = {
  loading: "Loading terrain…",
  "no-webgl": "The map needs WebGL, which this browser has turned off.",
  error: "The map could not load. Reload the page to try again.",
};

export interface TerrainMapProps {
  name: string;
  /** URL slug; used for a stable opening camera bearing per mountain. */
  slug?: string;
  lon: number;
  lat: number;
  /** Summit elevation. The relief tint turns white toward it. */
  elevationM: number;
  trails: Trail[];
  /** Live mountains get real tiles, history pins, and layer toggles when data exists. */
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
  /** A click on the map that hits no pin, with the selected cell coordinate. */
  onMapClick: (coordinate: { latitude: number; longitude: number }) => void;
  /** Past landslides for the pins. Empty until the catalog is downloaded. */
  historicalEvents: HistoricalEvent[];
  /** The hiker card's bypass: drawn dashed while the card is open, null otherwise. */
  bypass?: Bypass | null;
  /** The lettered top-five trails (A to E): a marker and a hover tooltip each. */
  trailMarkers?: TrailRisk[];
  /** The latest request to fly to a lettered trail. A new nonce flies again. */
  focus?: CameraFocus | null;
  /** A click on a lettered trail's marker, line, or region. Set it to fly there like View. */
  onTrailSelect?: (letter: TrailLetter) => void;
  /** The release to fly to when Simulate starts. A new nonce flies again. */
  release?: ReleaseCamera | null;
  /** The current runout footprint. Null before a simulation and after it is cleared. */
  flow?: FlowFeatureCollection | null;
  /** Dims the probability heat map while the flow is on screen. */
  flowActive?: boolean;
}

const NO_TRAIL_MARKERS: TrailRisk[] = [];
/** Steep enough to look up the slope at the runout's front on the 3D terrain. */
const FRONT_PITCH = 60;
const EMPTY_FLOW: FlowFeatureCollection = { type: "FeatureCollection", features: [] };

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
function fadeIn(map: MapLibreMap, layer: string, source: string, opacity = 1): () => void {
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
    map.setPaintProperty(layer, "raster-opacity", opacity);
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

/** Catalog peaks: API points at /tiles/synthetic/…; we paint one client image instead (no tile pop-in). */
function isProceduralHeat(layer: LayerTiles): boolean {
  return layer.tiles.includes("/tiles/synthetic/");
}

/** Drop whichever heat source was on the map so the other mode can attach cleanly. */
function removeHeatLayer(map: MapLibreMap, layerId: string, sourceId: string) {
  if (map.getLayer(layerId)) {
    map.removeLayer(layerId);
  }
  if (map.getSource(sourceId)) {
    map.removeSource(sourceId);
  }
}

/**
 * The mountain map: 3D terrain, a light shaded relief (or satellite with a Mapbox token),
 * pre-rendered susceptibility tiles on live peaks, one-shot seeded image on catalog peaks, and trails.
 * Browser-only. Load it through ./mountain-map.tsx.
 */
export default function TerrainMap({
  name,
  slug,
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
  historicalEvents: _historicalEvents,
  bypass = null,
  trailMarkers = NO_TRAIL_MARKERS,
  focus = null,
  onTrailSelect,
  release = null,
  flow = null,
  flowActive = false,
}: TerrainMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [webgl] = useState(hasWebGL);
  const [status, setStatus] = useState<MapStatus>(webgl ? "loading" : "no-webgl");
  const renderedHeat = useMemo(() => {
    if (probability) {
      return probability;
    }
    if (susceptibility && !isProceduralHeat(susceptibility)) {
      return susceptibility;
    }
    return null;
  }, [probability, susceptibility]);
  const instantHeat = useMemo(() => {
    const drapeBounds = heatDrapeBounds(lon, lat, elevationM);
    if (renderedHeat) {
      return null;
    }
    if (susceptibility && isProceduralHeat(susceptibility)) {
      return buildSyntheticHeatOverlay(slug ?? name, lon, lat, drapeBounds);
    }
    return buildSyntheticHeatOverlay(slug ?? name, lon, lat, drapeBounds);
  }, [renderedHeat, susceptibility, slug, name, lon, lat, elevationM]);
  // The camera frames the markers the page opened with. Later updates only move the markers.
  const markersAtOpen = useRef(trailMarkers);
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
    // Open on the mountain's footprint, sized from its elevation, plus the trail markers near it.
    const bounds = openingBounds(lon, lat, elevationM, markersAtOpen.current.map((trail) => trail.center));
    const bearing = openingBearing(lon, lat, slug);
    const instance = new MapLibreMap({
      container: container.current,
      style: mountainStyle({ summitM: elevationM, lon, lat, mapboxToken: process.env.NEXT_PUBLIC_MAPBOX_TOKEN || undefined }),
      center: [lon, lat],
      zoom: CAMERA.zoom,
      pitch: CAMERA.pitch,
      bearing,
      maxPitch: CAMERA.maxPitch,
      bounds,
      fitBoundsOptions: { padding: CAMERA.padding, pitch: CAMERA.pitch, bearing },
      attributionControl: { compact: true },
    });
    // The opening frame is the widest view that still reads as this mountain.
    instance.setMinZoom(instance.getZoom() - CAMERA.zoomOutRoom);
    instance.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
    instance.addControl(new ScaleControl({ unit: "imperial" }), "bottom-right");
    new Marker({ element: summitLabel(name), anchor: "bottom", offset: [0, -4] }).setLngLat([lon, lat]).addTo(instance);
    instance.once("load", () => {
      const zoomFloor = openingZoomFloor(slug);
      if (instance.getZoom() < zoomFloor) {
        instance.jumpTo({
          center: [lon, lat],
          zoom: zoomFloor,
          pitch: CAMERA.pitch,
          bearing,
        });
      }
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
  }, [name, slug, lon, lat, elevationM, webgl]);

  useEffect(() => {
    map?.getSource<GeoJSONSource>(SOURCE.trails)?.setData(trailFeatures(trails));
  }, [map, trails]);

  // Simulate flies once, before playback. Later frames do not move the camera. With the
  // footprint known, it frames all of it facing uphill, so the flow's front runs toward the viewer.
  useEffect(() => {
    if (!map || !release) {
      return;
    }
    if (release.bounds && release.bearing !== undefined) {
      map.fitBounds(release.bounds, {
        bearing: release.bearing,
        pitch: FRONT_PITCH,
        padding: 80,
        maxZoom: 15,
        duration: prefersReducedMotion() ? 0 : 1500,
      });
      return;
    }
    const camera = {
      center: [release.lon, release.lat] as [number, number],
      zoom: release.zoom,
      pitch: map.getPitch(),
      bearing: map.getBearing(),
    };
    if (prefersReducedMotion()) {
      map.jumpTo(camera);
    } else {
      map.flyTo({ ...camera, duration: 1500 });
    }
  }, [map, release]);

  // The debris-flow footprint, under the trails so trail color stays readable.
  // Core and margin use the risk ramp; the edge is the text color, not a level.
  useEffect(() => {
    if (!map) {
      return;
    }
    const data = flow ?? EMPTY_FLOW;
    const source = map.getSource<GeoJSONSource>(SOURCE.flow);
    if (source) {
      source.setData(data);
      if (map.getLayer(LAYER.flowEdge)) {
        map.setFilter(LAYER.flowEdge, ["==", ["get", "rim"], true]);
      }
      return;
    }
    map.addSource(SOURCE.flow, { type: "geojson", data });
    map.addLayer(
      {
        id: LAYER.flow,
        type: "fill",
        source: SOURCE.flow,
        paint: {
          // Dirt brown at the core, paling toward the sides. Bands stack edge first.
          "fill-color": [
            "match",
            ["get", "shade"],
            0,
            FLOW_COLORS[0],
            1,
            FLOW_COLORS[1],
            2,
            FLOW_COLORS[2],
            3,
            FLOW_COLORS[3],
            FLOW_COLORS[4],
          ],
          "fill-opacity": 0.85,
        },
      },
      LAYER.otherTrails,
    );
    map.addLayer(
      {
        id: LAYER.flowEdge,
        type: "line",
        source: SOURCE.flow,
        filter: ["==", ["get", "rim"], true],
        paint: { "line-color": "rgba(236, 230, 220, 0.7)", "line-width": 1.5 },
      },
      LAYER.otherTrails,
    );
  }, [map, flow]);

  useEffect(() => {
    const layer = map?.getLayer(LAYER.susceptibility)
      ? LAYER.susceptibility
      : map?.getLayer(LAYER.probability)
        ? LAYER.probability
        : null;
    if (!map || !layer) {
      return;
    }
    map.setPaintProperty(layer, "raster-opacity-transition", { duration: 0, delay: 0 });
    map.setPaintProperty(layer, "raster-opacity", flowActive ? 0.35 : 1);
  }, [map, flowActive, renderedHeat, instantHeat]);

  // Live peaks: saved probability tiles, or the pack's rendered susceptibility tiles.
  useEffect(() => {
    if (!map || !renderedHeat) {
      return;
    }
    removeHeatLayer(map, LAYER.probability, SOURCE.syntheticProbability);
    removeHeatLayer(map, LAYER.susceptibility, SOURCE.susceptibility);

    const isProbability = renderedHeat.layer === "probability";
    const layerId = isProbability ? LAYER.probability : LAYER.susceptibility;
    const sourceId = isProbability ? SOURCE.probability : SOURCE.susceptibility;
    removeHeatLayer(map, layerId, sourceId);

    const source = map.getSource<RasterTileSource>(sourceId);
    if (source) {
      source.setTiles([renderedHeat.tiles]);
    } else {
      map.addSource(sourceId, rasterSource(renderedHeat));
      map.addLayer(
        {
          id: layerId,
          type: "raster",
          source: sourceId,
          paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
        },
        LAYER.otherTrails,
      );
    }
    return fadeIn(map, layerId, sourceId, flowActive ? 0.35 : 1);
  }, [map, renderedHeat, flowActive]);

  // Catalog peaks: one canvas image (same seed as synthetic tiles, loads in one shot — no chunking).
  useEffect(() => {
    if (!map || !instantHeat?.url) {
      return;
    }
    removeHeatLayer(map, LAYER.susceptibility, SOURCE.susceptibility);

    const sourceId = SOURCE.syntheticProbability;
    const existing = map.getSource(sourceId) as ImageSource | undefined;
    if (existing?.updateImage) {
      existing.updateImage({ url: instantHeat.url, coordinates: instantHeat.coordinates });
    } else {
      removeHeatLayer(map, LAYER.probability, sourceId);
      map.addSource(sourceId, {
        type: "image",
        url: instantHeat.url,
        coordinates: instantHeat.coordinates,
      });
      map.addLayer(
        {
          id: LAYER.probability,
          type: "raster",
          source: sourceId,
          paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
        },
        LAYER.otherTrails,
      );
    }
    return fadeIn(map, LAYER.probability, sourceId, flowActive ? 0.35 : 1);
  }, [map, instantHeat, flowActive]);

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

  // The hiker card's bypass: dashed, colored by its own levels, above the trails. Other trails dim.
  useEffect(() => {
    if (!map || !isLive) {
      return;
    }
    const data = bypassFeatures(bypass);
    const source = map.getSource<GeoJSONSource>(SOURCE.bypass);
    if (source) {
      source.setData(data);
    } else {
      map.addSource(SOURCE.bypass, { type: "geojson", data });
      map.addLayer({
        id: LAYER.bypass,
        type: "line",
        source: SOURCE.bypass,
        layout: { "line-join": "round", "line-cap": "butt" },
        paint: { "line-color": HAZARD_OUTLINE_COLOR, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 3, 15, 6], "line-dasharray": [2, 1.5] },
      });
    }
    map.setPaintProperty(LAYER.otherTrails, "line-opacity", bypass ? DIMMED_TRAIL_OPACITY : 1);
    if (bypass) {
      const coords = bypass.geom.coordinates;
      const bounds = map.getBounds();
      if (!coords.every(([x, y]) => bounds.contains([x, y]))) {
        const lons = coords.map((c) => c[0]);
        const lats = coords.map((c) => c[1]);
        map.fitBounds([Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)], { padding: 60, duration: 0 });
      }
    }
  }, [map, isLive, bypass]);

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

  useEffect(() => {
    if (!map) {
      return;
    }
    const onClick = (event: MapMouseEvent) => {
      mapClick.current({ latitude: event.lngLat.lat, longitude: event.lngLat.lng });
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
    };
  }, [map]);

  useTrailMarkers(map, trailMarkers, focus, onTrailSelect);
  // No orbit while a runout is framed: turning would carry its front out of view.
  useIdleOrbit(map, Boolean(focus) || Boolean(release));

  return (
    <div className="absolute inset-0">
      {/* MapLibre's stylesheet sets the container to position: relative, so size it by height. */}
      <div ref={container} className="h-full w-full" />
      {status !== "ready" && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <p className="rounded-lg border border-border bg-popover px-3 py-2 text-sm text-muted-foreground">{STATUS_TEXT[status]}</p>
        </div>
      )}
    </div>
  );
}
