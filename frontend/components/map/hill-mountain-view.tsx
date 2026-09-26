"use client";

import type { CameraFocus, TrailRisk } from "@/lib/hill";
import type { LayerTiles, MountainDetail } from "@/lib/types";
import MountainMap from "./mountain-map";

export interface HillMountainViewProps {
  mountain: MountainDetail;
  probability: LayerTiles | null;
  susceptibility: LayerTiles | null;
  /** The top five, lettered A to E. Each gets a marker at its center. */
  trails: TrailRisk[];
  /** The latest "View" click. Null until the first one. */
  focus: CameraFocus | null;
}

function noop() {}

/**
 * The hill card's left column: the 3D terrain map with its heat map, trails, and layer
 * toggles, plus a lettered marker per top-five trail. A "View" click (a new `focus`) flies
 * the camera to that trail's region. Fills its `relative` parent.
 */
export default function HillMountainView({ mountain, probability, susceptibility, trails, focus }: HillMountainViewProps) {
  return (
    <div className="absolute inset-0 overflow-hidden bg-muted">
      <MountainMap
        key={mountain.slug}
        name={mountain.name}
        lon={mountain.lon}
        lat={mountain.lat}
        elevationM={mountain.elevation_m}
        trails={mountain.trails}
        isLive={mountain.is_live}
        probability={probability}
        susceptibility={susceptibility}
        hazard={mountain.active_hazard}
        hazardSelected={false}
        onHazardClick={noop}
        onMapClick={noop}
        historicalEvents={mountain.historical_events}
        trailMarkers={trails}
        focus={focus}
      />
    </div>
  );
}
