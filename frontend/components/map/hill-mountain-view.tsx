"use client";

import type { CameraFocus, TrailLetter, TrailRisk } from "@/lib/hill";
import type { LayerTiles, MountainDetail } from "@/lib/types";
import MountainMap from "./mountain-map";

export interface HillMountainViewProps {
  mountain: MountainDetail;
  probability: LayerTiles | null;
  susceptibility: LayerTiles | null;
  /** The top five, lettered A to E. Each gets a marker at its center. */
  trails: TrailRisk[];
  /** The latest "View" click, or click on a trail on the map. Null until the first one. */
  focus: CameraFocus | null;
  /** A click on a trail on the map: the same as its View button. */
  onTrailSelect: (letter: TrailLetter) => void;
  /** A click on an empty map cell selects it for the production classifier. */
  onMapClick: (coordinate: { latitude: number; longitude: number }) => void;
}

function noop() {}

/**
 * The hill card's left column: the 3D terrain map with its heat map, trails, and layer
 * toggles, plus a lettered marker per top-five trail. A "View" click or a click on the trail on
 * the map (a new `focus`) flies the camera to that trail's region. Fills its `relative` parent.
 */
export default function HillMountainView({
  mountain,
  probability,
  susceptibility,
  trails,
  focus,
  onTrailSelect,
  onMapClick,
}: HillMountainViewProps) {
  return (
    <div className="absolute inset-0 overflow-hidden bg-muted">
      <MountainMap
        key={mountain.slug}
        name={mountain.name}
        slug={mountain.slug}
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
        onMapClick={onMapClick}
        historicalEvents={mountain.historical_events}
        trailMarkers={trails}
        focus={focus}
        onTrailSelect={onTrailSelect}
      />
    </div>
  );
}
