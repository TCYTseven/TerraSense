"use client";

import dynamic from "next/dynamic";
import type { TerrainMapProps } from "./terrain-map";

// MapLibre needs WebGL and the DOM, so the map renders in the browser only.
const TerrainMap = dynamic(() => import("./terrain-map"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-surface" />,
});

/** The map area of /mountains/[slug]. */
export default function MountainMap(props: TerrainMapProps) {
  return <TerrainMap {...props} />;
}
