import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  LngLatBoundsLike,
  RasterSourceSpecification,
  SourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import { RISK_COLORS, THEME } from "@/lib/theme";
import type { Bypass, Hazard, HistoricalEvent, LayerTiles, LineString, RiskLevel, Trail } from "@/lib/types";

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
  /** How far below the opening zoom the user may zoom out: one level, about twice the view. */
  zoomOutRoom: 1,
  /** The idle orbit: a full turn in about five minutes, resuming after 8 s without input. */
  orbitDegPerSec: 1.2,
  orbitResumeMs: 8000,
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
  susceptibility: "susceptibility",
  probability: "probability",
  hazard: "hazard",
  bypass: "bypass",
  history: "historical-events",
  trailRisk: "trail-risk",
} as const;

export const LAYER = {
  background: "background",
  satellite: "satellite",
  tint: "elevation-tint",
  hillshade: "hillshade",
  susceptibility: "susceptibility",
  probability: "probability",
  hazardOutline: "hazard-outline",
  otherTrails: "trails-other",
  heroCasing: "trail-hero-casing",
  heroLine: "trail-hero",
  bypass: "bypass-line",
  history: "historical-pins",
  trailRisk: "trail-risk-line",
} as const;

/**
 * A raster layer from GET /mountains/{slug}/layers/{layer}. Color and alpha are baked into
 * the PNG tiles, so the layer paints at full opacity. Past the source's maxzoom the map
 * stretches the deepest tiles.
 */
export function rasterSource(layer: LayerTiles): RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [layer.tiles],
    tileSize: 256,
    bounds: layer.bounds,
    minzoom: layer.minzoom,
    maxzoom: layer.maxzoom,
  };
}

/** The heat map fades in over this long when it first shows and when a run brings new tiles. */
export const HEAT_FADE_MS = 600;

/** The active hazard's zone, carrying its level for the outline color. */
export function hazardFeatures(
  hazard: Hazard | null,
): GeoJSON.FeatureCollection<GeoJSON.Polygon, { severity: RiskLevel }> {
  return {
    type: "FeatureCollection",
    features: hazard ? [{ type: "Feature", geometry: hazard.geom, properties: { severity: hazard.severity } }] : [],
  };
}

/** The hazard zone: a 2 px outline in its level color. No fill: the heat map already fills it. */
export const HAZARD_OUTLINE_COLOR: ExpressionSpecification = [
  "match",
  ["get", "severity"],
  "low",
  RISK_COLORS.low,
  "moderate",
  RISK_COLORS.moderate,
  "high",
  RISK_COLORS.high,
  RISK_COLORS.extreme,
];

/** The bypass, piece by piece, each colored by its own level (step 25, hiker card only). */
export function bypassFeatures(
  bypass: Bypass | null,
): GeoJSON.FeatureCollection<GeoJSON.LineString, { severity: RiskLevel }> {
  return {
    type: "FeatureCollection",
    features: (bypass?.pieces ?? []).map((piece) => ({
      type: "Feature",
      geometry: piece.geom,
      properties: { severity: piece.level },
    })),
  };
}

/** The lettered top-five trails that have a line, each carrying its level and letter. */
export function trailRiskFeatures(
  trails: { letter: string; level: RiskLevel; geom: LineString | null }[],
): GeoJSON.FeatureCollection<GeoJSON.LineString, { severity: RiskLevel; letter: string }> {
  return {
    type: "FeatureCollection",
    features: trails.flatMap((trail) =>
      trail.geom ? [{ type: "Feature" as const, geometry: trail.geom, properties: { severity: trail.level, letter: trail.letter } }] : [],
    ),
  };
}

/**
 * A lettered trail's line: a thin, half-strength stroke in its level color over the dashed
 * context line, a little heavier when its letter is selected. Subtle on purpose: the markers
 * and the heat map carry the finding.
 */
export function trailRiskPaint(selected: string | null) {
  const isSelected: ExpressionSpecification = ["==", ["get", "letter"], selected ?? ""];
  return {
    width: [
      "interpolate",
      ["linear"],
      ["zoom"],
      10,
      ["case", isSelected, 2.5, 1.5],
      15,
      ["case", isSelected, 5, 3],
    ] as ExpressionSpecification,
    opacity: ["case", isSelected, 0.9, 0.6] as ExpressionSpecification,
  };
}

/** Other trails drop to this opacity while the hiker card draws the bypass. */
export const DIMMED_TRAIL_OPACITY = 0.35;

type HistoryProperties = {
  id: string;
  date: string | null;
  category: string | null;
  source_name: string | null;
  source_link: string | null;
  catalog: string;
};

/** Past landslides as map points, carrying what the pin popup shows. */
export function historyFeatures(
  events: HistoricalEvent[],
): GeoJSON.FeatureCollection<GeoJSON.Point, HistoryProperties> {
  return {
    type: "FeatureCollection",
    features: events.map((event) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [event.lon, event.lat] },
      properties: {
        id: event.id,
        date: event.date,
        category: event.category,
        source_name: event.source_name,
        source_link: event.source_link,
        catalog: event.catalog,
      },
    })),
  };
}

/**
 * Historical pins: small circles in the text color with a dark ring. Not a risk color,
 * because a past event is not today's level.
 */
export const HISTORY_LAYER: CircleLayerSpecification = {
  id: LAYER.history,
  type: "circle",
  source: SOURCE.history,
  paint: {
    "circle-radius": 4,
    "circle-color": THEME.foreground,
    "circle-opacity": 0.85,
    "circle-stroke-width": 1.5,
    "circle-stroke-color": THEME.background,
  },
};

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
