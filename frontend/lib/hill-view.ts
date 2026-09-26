import { buildHillView as illustrativeHillView } from "./fixtures/hill-demo";
import { TRAIL_LETTERS, type HillView, type TrailRisk } from "./hill";
import type { MountainDetail, TrailRiskView } from "./types";

/** The zoom "View" flies to around a trail's worst point. */
const TRAIL_FOCUS_ZOOM = 13.2;

/**
 * The hill card's view model. A live mountain takes its trails, overall score, stats, and
 * preventative measures from GET /mountains/{slug}/trail-risk, which reads them off the
 * current probability map. When that endpoint does not answer, the card falls back to the
 * illustrative fixture and says so.
 */
export function buildHillView(mountain: MountainDetail, trailRisk: TrailRiskView | null): HillView {
  if (!mountain.is_live || trailRisk === null) {
    return illustrativeHillView(mountain);
  }
  const byId = new Map(mountain.trails.map((trail) => [trail.id, trail]));
  const trails: TrailRisk[] = trailRisk.trails.slice(0, TRAIL_LETTERS.length).map((entry, index) => {
    const trail = byId.get(entry.trail_id);
    const coordinates = trail?.geom.coordinates;
    // The marker sits on the trail's worst point. Without one, the middle of its line.
    const center = entry.point ?? coordinates?.[Math.floor((coordinates.length - 1) / 2)] ?? [mountain.lon, mountain.lat];
    return {
      id: entry.trail_id,
      letter: TRAIL_LETTERS[index],
      name: entry.name,
      score: entry.score,
      level: entry.level,
      slopeDeg: entry.slope_deg,
      primaryFactor: entry.primary_factor,
      center: [center[0], center[1]],
      zoom: TRAIL_FOCUS_ZOOM,
      geom: trail?.geom ?? null,
    };
  });
  return {
    slug: mountain.slug,
    name: mountain.name,
    region: mountain.region,
    isLive: true,
    stats: {
      elevationM: mountain.elevation_m,
      meanSlopeDeg: trailRisk.mean_slope_deg,
      areaKm2: trailRisk.area_km2,
    },
    risk: { score: trailRisk.score, level: trailRisk.level },
    trails,
    preventative: trailRisk.preventative,
    isDemo: false,
    scoreSource: trailRisk.source,
  };
}
