"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import {
  type GeoJSONSource,
  type MapLayerMouseEvent,
  MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
  type RasterTileSource,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { formatDate, humanize } from "@/lib/format";
import type { HistoricalEvent, LayerTiles, Trail } from "@/lib/types";
import LayerToggles from "./layer-toggles";
import {
  CAMERA,
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
  /** The susceptibility tiles, or null when the layer is not rendered. */
  susceptibility: LayerTiles | null;
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
  susceptibility,
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
