import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  RasterSourceSpecification,
  SourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import { RISK_COLORS, THEME } from "@/lib/theme";
import type { Bypass, Hazard, HistoricalEvent, LayerTiles, LineString, Position, RiskLevel, Trail } from "@/lib/types";

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
  /** How far below the opening zoom the user may zoom out: a third of a level, about 1.25x the view. */
  zoomOutRoom: 0.33,
  /** The idle orbit: a full turn in about five minutes, resuming after 8 s without input. */
  orbitDegPerSec: 1.2,
  orbitResumeMs: 8000,
  // Extra room at the top: the exaggerated summit rises above where its base sits on screen.
  padding: { top: 150, bottom: 48, left: 48, right: 48 },
  /** Rainier's relief is tall; pitched views need more headroom so the summit stays in frame. */
  rainierPadding: { top: 280, bottom: 64, left: 48, right: 48 },
  /** After fitBounds, never open wider than this — keeps massifs readable on screen. */
  openingZoomFloor: 11.45,
} as const;

/** Keep Kailash close enough for its summit relief to dominate instead of its 52 km kora. */
export function openingZoomFloor(slug?: string): number {
  return slug === "mount-kailash" ? 12.25 : CAMERA.openingZoomFloor;
}

/** fitBounds padding for the opening frame (summit relief vs. pitch). */
export function openingFitPadding(slug?: string): { top: number; bottom: number; left: number; right: number } {
  return slug === "mount-rainier" ? CAMERA.rainierPadding : CAMERA.padding;
}

/** Oblique opening bearing: Rainier keeps the designed bearing; others get a stable view from coords. */
export function openingBearing(lon: number, lat: number, slug?: string): number {
  if (slug === "mount-rainier") {
    return CAMERA.bearing;
  }
  const normalized = (((lon * 1.7 + lat * 2.3) % 360) + 360) % 360;
  return normalized - 180;
}

/** Map-only colors. Risk colors come from lib/theme.ts and mark risk only. */
export const MAP_COLORS = {
  /** The page behind the map and the sky above it, so the horizon fades into the page. */
  paper: "#EEF1F5",
  /**
   * Elevation tint: valleys stay a cool off-white, and the mountain itself, from its base up to
   * the summit, is gray, so the massif reads at a glance without washing out.
   */
  tint: ["#E8ECF1", "#DDE3EA", "#A3ADB8", "#8A96A3", "#75808D"],
  /** The wash that fades everything outside the mountain's footprint back to the valley tint. */
  surround: "#E8ECF1",
  /** Slopes turned away from the light. */
  shadow: "#334155",
  /** Slopes facing the light. */
  highlight: "#E8EDF2",
  /** Sharp breaks: ridgelines and gully walls. */
  accent: "#5C6A78",
  /** The hero trail before the model scores it. */
  trail: "#0F172A",
  /** Every other trail: context, not a finding. */
  otherTrail: "#334155",
  /** The halo under the hero trail, so it reads on light and dark ground. */
  casing: "#FFFFFF",
} as const;

// Where each tint color starts, as a share of the summit's height. White through the valleys,
// foothills, and neighboring ridges (up to about 42% of the summit), then gray from the
// mountain's upper flanks to the top.
const TINT_STOPS = [0, 0.42, 0.5, 0.7, 1];

/**
 * The surround wash outside the footprint, as [inner radius, outer radius] in footprint radii
 * and its opacity. Four rings feather the edge so no hard circle shows on the ground.
 */
const SURROUND_RINGS = [
  [1.1, 1.25, 0.2],
  [1.25, 1.4, 0.4],
  [1.4, 1.6, 0.6],
  [1.6, 12, 0.8],
] as const;

export const SOURCE = {
  terrain: "terrain-dem",
  relief: "relief-dem",
  satellite: "satellite",
  trails: "trails",
  surround: "surround",
  susceptibility: "susceptibility",
  probability: "probability",
  syntheticProbability: "synthetic-probability",
  syntheticAura: "synthetic-aura",
  hazard: "hazard",
  bypass: "bypass",
  history: "historical-events",
  trailRisk: "trail-risk",
  flow: "runout-flow",
  flowField: "runout-field",
} as const;

export const LAYER = {
  background: "background",
  satellite: "satellite",
  tint: "elevation-tint",
  surround: "surround-wash",
  hillshade: "hillshade",
  susceptibility: "susceptibility",
  probability: "probability",
  syntheticAura: "synthetic-aura",
  hazardOutline: "hazard-outline",
  otherTrails: "trails-other",
  heroCasing: "trail-hero-casing",
  heroLine: "trail-hero",
  bypass: "bypass-line",
  history: "historical-pins",
  trailRisk: "trail-risk-line",
  flow: "runout-flow",
  flowEdge: "runout-flow-edge",
  flowField: "runout-field",
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

/**
 * How far a mountain's base spreads from its summit, per meter of summit elevation. Flanks
 * average about 22°, so the base sits roughly relief / tan(22°) out; relief is taken as 85% of
 * the summit elevation, since the surrounding valleys are rarely at sea level.
 * 0.85 / tan(22°) ≈ 2.1: about 9 km for Rainier, 19 km for Everest.
 */
export const FOOTPRINT_PER_M = 0.85 / Math.tan((22 * Math.PI) / 180);
/** The framed radius stays readable for small hills and giant massifs alike. */
export const FOOTPRINT_KM = { min: 3, max: 25 } as const;

const KM_PER_DEG = 111.32;

/** The mountain's footprint radius in km, from its summit elevation (see FOOTPRINT_PER_M). */
export function footprintRadiusKm(elevationM: number): number {
  return Math.min(FOOTPRINT_KM.max, Math.max(FOOTPRINT_KM.min, (FOOTPRINT_PER_M * elevationM) / 1000));
}

/**
 * Geographic bounds for the catalog heat drape. It reaches past the footprint so its faded rim
 * lands under the surround wash (which starts at 1.1x) instead of ending on the relief.
 */
export function heatDrapeBounds(lon: number, lat: number, elevationM: number): [number, number, number, number] {
  const radiusKm = footprintRadiusKm(elevationM) * 1.3;
  const kmPerDegLon = KM_PER_DEG * Math.cos((lat * Math.PI) / 180);
  const dLat = radiusKm / KM_PER_DEG;
  const dLon = radiusKm / kmPerDegLon;
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
}

/** A closed ring of `steps` points at `radiusKm` around a point, in [lon, lat]. */
function circle(lon: number, lat: number, radiusKm: number, steps = 96): Position[] {
  const kmPerDegLon = KM_PER_DEG * Math.cos((lat * Math.PI) / 180);
  const ring: Position[] = [];
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    ring.push([lon + (radiusKm * Math.cos(a)) / kmPerDegLon, lat + (radiusKm * Math.sin(a)) / KM_PER_DEG]);
  }
  return ring;
}

/** The feathered rings outside the footprint, each a donut polygon with its wash opacity. */
function surroundFeatures(lon: number, lat: number, elevationM: number): GeoJSON.FeatureCollection {
  const r = footprintRadiusKm(elevationM);
  return {
    type: "FeatureCollection",
    features: SURROUND_RINGS.map(([inner, outer, opacity]) => ({
      type: "Feature",
      properties: { opacity },
      geometry: {
        type: "Polygon",
        // Outer ring, then the hole (reversed so it winds the other way).
        coordinates: [circle(lon, lat, r * outer), circle(lon, lat, r * inner).reverse()],
      },
    })),
  };
}

/**
 * The opening frame for any mountain: a circle around the summit sized by its elevation (see
 * FOOTPRINT_PER_M), stretched to take in the points of interest (the trail markers) that sit
 * within twice that radius, so far-off outliers can't pull the view away from the mountain.
 */
export function openingBounds(
  lon: number,
  lat: number,
  elevationM: number,
  points: Position[] = [],
  slug?: string,
): [number, number, number, number] {
  const radiusKm = footprintRadiusKm(elevationM);
  const kmPerDegLon = KM_PER_DEG * Math.cos((lat * Math.PI) / 180);
  const dLat = radiusKm / KM_PER_DEG;
  const dLon = radiusKm / kmPerDegLon;
  // Only nearby trail markers may widen the frame. Long loops (e.g. the Kailash kora) sit
  // mostly outside the summit footprint; pulling them in would zoom out until trails vanish.
  const near = points.filter(
    ([x, y]) => Math.hypot((x - lon) * kmPerDegLon, (y - lat) * KM_PER_DEG) <= radiusKm * 1.15,
  );
  const lons = [lon - dLon, lon + dLon, ...near.map(([x]) => x)];
  const lats = [lat - dLat, lat + dLat, ...near.map(([, y]) => y)];
  let south = Math.min(...lats);
  let north = Math.max(...lats);
  if (slug === "mount-rainier") {
    north = Math.max(north, lat + dLat * 0.55);
  }
  return [Math.min(...lons), south, Math.max(...lons), north];
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

export function mountainStyle({
  summitM,
  lon,
  lat,
  mapboxToken,
}: {
  summitM: number;
  lon: number;
  lat: number;
  mapboxToken?: string;
}): StyleSpecification {
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
    [SOURCE.surround]: { type: "geojson", data: surroundFeatures(lon, lat, summitM) },
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
          "hillshade-exaggeration": satellite ? 0.22 : 0.48,
          "hillshade-shadow-color": MAP_COLORS.shadow,
          "hillshade-highlight-color": MAP_COLORS.highlight,
          "hillshade-accent-color": MAP_COLORS.accent,
        },
      },
      // Neighboring ridges can be as high as the mountain's flanks, so the ground outside its
      // footprint fades back to white, over the hillshade, so only a faint relief shows there.
      {
        id: LAYER.surround,
        type: "fill",
        source: SOURCE.surround,
        layout: { visibility: satellite ? "none" : "visible" },
        paint: { "fill-color": MAP_COLORS.surround, "fill-opacity": ["get", "opacity"], "fill-antialias": false },
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
