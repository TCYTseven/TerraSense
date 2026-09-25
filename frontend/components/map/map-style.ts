import type {
  ExpressionSpecification,
  LngLatBoundsLike,
  SourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import { RISK_COLORS } from "@/lib/theme";
import type { RiskLevel, Trail } from "@/lib/types";

/**
 * The mountain map's style: 3D terrain from open elevation tiles under a light shaded relief.
 * With NEXT_PUBLIC_MAPBOX_TOKEN set, Mapbox satellite imagery replaces the relief's tint.
 */

// AWS Terrain Tiles: global elevation in the Terrarium PNG encoding, free and keyless.
const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const TERRAIN_MAXZOOM = 15;
const TERRAIN_ATTRIBUTION =
  '<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">Terrain Tiles</a> (Mapzen, AWS Open Data)';
const TRAIL_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Vertical exaggeration of the 3D terrain. */
export const TERRAIN_EXAGGERATION = 1.5;

/**
 * The opening camera, tilted so the relief reads as 3D. The bearing looks from Paradise up
 * to Rainier's summit. With no hero trail, the map centers on the summit at `zoom`.
 */
export const CAMERA = {
  zoom: 11.6,
  pitch: 55,
  bearing: -14,
  maxPitch: 70,
  // Extra room at the top: the exaggerated summit rises above where its base sits on screen.
  padding: { top: 150, bottom: 48, left: 48, right: 48 },
} as const;

/** Map-only colors. Risk colors come from lib/theme.ts and mark risk only. */
export const MAP_COLORS = {
  /** The page behind the map and the sky above it, so the horizon fades into the page. */
  paper: "#F4F6F8",
  /** Elevation tint, valley floor to summit: cool gray rising to white snow. */
  tint: ["#D5DDE5", "#DFE5EB", "#ECF0F4", "#F8FAFB", "#FFFFFF"],
  /** Slopes turned away from the light. */
  shadow: "#334155",
  /** Slopes facing the light. */
  highlight: "#FFFFFF",
  /** Sharp breaks: ridgelines and gully walls. */
  accent: "#64748B",
  /** The hero trail before the model scores it. */
  trail: "#0F172A",
  /** Every other trail: context, not a finding. */
  otherTrail: "#334155",
  /** The halo under the hero trail, so it reads on light and dark ground. */
  casing: "#FFFFFF",
} as const;

// Where each tint color starts, as a share of the summit's height.
const TINT_STOPS = [0, 0.25, 0.45, 0.6, 0.8];

export const SOURCE = {
  terrain: "terrain-dem",
  relief: "relief-dem",
  satellite: "satellite",
  trails: "trails",
} as const;

export const LAYER = {
  background: "background",
  satellite: "satellite",
  tint: "elevation-tint",
  hillshade: "hillshade",
  otherTrails: "trails-other",
  heroCasing: "trail-hero-casing",
  heroLine: "trail-hero",
} as const;

function demSource(): SourceSpecification {
  return {
    type: "raster-dem",
    tiles: [TERRAIN_TILES],
    encoding: "terrarium",
    tileSize: 256,
    maxzoom: TERRAIN_MAXZOOM,
    attribution: TERRAIN_ATTRIBUTION,
  };
}

/** The hero trail is the one with segments: the model scores it mile by mile. */
export function isHero(trail: Trail): boolean {
  return trail.segments.length > 0;
}

type TrailProperties = { trail: string; hero: boolean; risk: RiskLevel | null };

/** The hero trail as its segments, each with its risk. Every other trail as one line. */
export function trailFeatures(trails: Trail[]): GeoJSON.FeatureCollection<GeoJSON.LineString, TrailProperties> {
  const features = trails.flatMap((trail): GeoJSON.Feature<GeoJSON.LineString, TrailProperties>[] => {
    if (!isHero(trail)) {
      return [{ type: "Feature", geometry: trail.geom, properties: { trail: trail.name, hero: false, risk: null } }];
    }
    return trail.segments.map((segment) => ({
      type: "Feature",
      geometry: segment.geom,
      properties: { trail: trail.name, hero: true, risk: segment.risk_level },
    }));
  });
  return { type: "FeatureCollection", features };
}

/** The summit and the hero trail, [west, south, east, north], or null without a hero trail. */
export function openingBounds(lon: number, lat: number, trails: Trail[]): LngLatBoundsLike | null {
  const points = trails.filter(isHero).flatMap((trail) => trail.geom.coordinates);
  if (points.length === 0) {
    return null;
  }
  const lons = [lon, ...points.map(([x]) => x)];
  const lats = [lat, ...points.map(([, y]) => y)];
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

// Scored segments take their risk color. Unscored ones stay a neutral ink line.
const HERO_COLOR: ExpressionSpecification = [
  "match",
  ["coalesce", ["get", "risk"], "none"],
  "low",
  RISK_COLORS.low,
  "moderate",
  RISK_COLORS.moderate,
  "high",
  RISK_COLORS.high,
  "extreme",
  RISK_COLORS.extreme,
  MAP_COLORS.trail,
];

// Line widths grow with zoom so the trails stay readable at the opening view and up close.
const byZoom = (atTen: number, atFifteen: number): ExpressionSpecification => [
  "interpolate",
  ["linear"],
  ["zoom"],
  10,
  atTen,
  15,
  atFifteen,
];

function elevationTint(summitM: number): ExpressionSpecification {
  const stops = TINT_STOPS.flatMap((share, i) => [Math.round(share * summitM), MAP_COLORS.tint[i]]);
  return ["interpolate", ["linear"], ["elevation"], ...stops] as ExpressionSpecification;
}

export function mountainStyle({ summitM, mapboxToken }: { summitM: number; mapboxToken?: string }): StyleSpecification {
  const satellite = Boolean(mapboxToken);
  const sources: StyleSpecification["sources"] = {
    [SOURCE.terrain]: demSource(),
    // The tint and the hillshade read the same tiles through a second source, as MapLibre
    // recommends when one DEM drives both the 3D terrain and flat layers.
    [SOURCE.relief]: demSource(),
    [SOURCE.trails]: {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      attribution: TRAIL_ATTRIBUTION,
    },
  };
  if (satellite) {
    sources[SOURCE.satellite] = {
      type: "raster",
      tiles: [`https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90?access_token=${mapboxToken}`],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.mapbox.com/about/maps/">Mapbox</a> © Maxar',
    };
  }

  return {
    version: 8,
    sources,
    layers: [
      { id: LAYER.background, type: "background", paint: { "background-color": MAP_COLORS.paper } },
      satellite
        ? { id: LAYER.satellite, type: "raster", source: SOURCE.satellite }
        : { id: LAYER.tint, type: "color-relief", source: SOURCE.relief, paint: { "color-relief-color": elevationTint(summitM) } },
      {
        id: LAYER.hillshade,
        type: "hillshade",
        source: SOURCE.relief,
        paint: {
          // Imagery already carries shadows, so the relief only sharpens it.
          "hillshade-exaggeration": satellite ? 0.2 : 0.4,
          "hillshade-shadow-color": MAP_COLORS.shadow,
          "hillshade-highlight-color": MAP_COLORS.highlight,
          "hillshade-accent-color": MAP_COLORS.accent,
        },
      },
      {
        id: LAYER.otherTrails,
        type: "line",
        source: SOURCE.trails,
        filter: ["!", ["get", "hero"]],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": MAP_COLORS.otherTrail,
          "line-width": byZoom(1.2, 2.5),
          "line-dasharray": [2, 1.5],
        },
      },
      {
        id: LAYER.heroCasing,
        type: "line",
        source: SOURCE.trails,
        filter: ["get", "hero"],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": MAP_COLORS.casing, "line-width": byZoom(5, 10), "line-opacity": 0.95 },
      },
      {
        id: LAYER.heroLine,
        type: "line",
        source: SOURCE.trails,
        filter: ["get", "hero"],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": HERO_COLOR, "line-width": byZoom(2.5, 5.5) },
      },
    ],
    terrain: { source: SOURCE.terrain, exaggeration: TERRAIN_EXAGGERATION },
    sky: {
      "sky-color": MAP_COLORS.paper,
      "horizon-color": MAP_COLORS.paper,
      "fog-color": MAP_COLORS.paper,
      "sky-horizon-blend": 0.6,
      "horizon-fog-blend": 0.6,
      "fog-ground-blend": 0.4,
      "atmosphere-blend": 0,
    },
  };
}
