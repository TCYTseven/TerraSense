"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import {
  type GeoJSONSource,
  MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { Trail } from "@/lib/types";
import { CAMERA, mountainStyle, openingBounds, SOURCE, trailFeatures } from "./map-style";

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
  lon: number;
  lat: number;
  /** Summit elevation. The relief tint turns white toward it. */
  elevationM: number;
  trails: Trail[];
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

function hasWebGL(): boolean {
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

/**
 * The mountain map: 3D terrain, a light shaded relief (or satellite with a Mapbox token),
 * and the trails. Browser-only. Load it through ./mountain-map.tsx.
 */
export default function TerrainMap({ name, lon, lat, elevationM, trails }: TerrainMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [webgl] = useState(hasWebGL);
  const [status, setStatus] = useState<MapStatus>(webgl ? "loading" : "no-webgl");
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
