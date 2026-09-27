/** Preset views for the home globe region picker. */
export type GlobeRegionId =
  | "world"
  | "northAmerica"
  | "centralAmerica"
  | "southAmerica"
  | "europe"
  | "africa"
  | "middleEast"
  | "asia"
  | "oceania";

export interface GlobeRegion {
  id: GlobeRegionId;
  label: string;
  lat: number;
  lon: number;
  /** Camera distance from the globe center. Surface is at 1. */
  distance: number;
  /** Idle spin runs only in whole-globe mode. */
  allowIdleSpin: boolean;
}

export const GLOBE_REGIONS: readonly GlobeRegion[] = [
  { id: "world", label: "Whole globe", lat: 0, lon: 0, distance: 3.4, allowIdleSpin: true },
  { id: "northAmerica", label: "North America", lat: 39.5, lon: -98.5, distance: 2.15, allowIdleSpin: false },
  { id: "centralAmerica", label: "Central America", lat: 14, lon: -87, distance: 2.05, allowIdleSpin: false },
  { id: "southAmerica", label: "South America", lat: -18, lon: -64, distance: 2.05, allowIdleSpin: false },
  { id: "europe", label: "Europe", lat: 52, lon: 12, distance: 2.05, allowIdleSpin: false },
  { id: "africa", label: "Africa", lat: 4, lon: 22, distance: 2.05, allowIdleSpin: false },
  { id: "middleEast", label: "Middle East", lat: 28, lon: 44, distance: 2.05, allowIdleSpin: false },
  { id: "asia", label: "Asia", lat: 34, lon: 98, distance: 2.05, allowIdleSpin: false },
  { id: "oceania", label: "Oceania", lat: -25.5, lon: 134, distance: 2.15, allowIdleSpin: false },
] as const;

export function globeRegionById(id: GlobeRegionId): GlobeRegion {
  return GLOBE_REGIONS.find((region) => region.id === id) ?? GLOBE_REGIONS[0]!;
}
