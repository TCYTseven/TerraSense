import { TRAIL_LETTERS, type HillView, type TrailRisk } from "../hill";
import type { MountainDetail, RiskLevel } from "../types";

/**
 * The hill card's fallback view model, used only when GET /mountains/{slug}/trail-risk does
 * not answer (see `lib/hill-view.ts`). Names, midpoints, and the mountain's own fields are
 * real; scores, slopes, and factors are not model output, so the view is marked `isDemo`.
 */

/** Shared fact: Rainier's box, [west, south, east, north]. */
export const RAINIER_BBOX = [-121.93, 46.76, -121.54, 46.96] as const;

/** Shared fact: the probability bins. */
export function levelForScore(score: number): RiskLevel {
  if (score > 0.7) return "extreme";
  if (score >= 0.45) return "high";
  if (score >= 0.2) return "moderate";
  return "low";
}

const KM_PER_DEG_LAT = 111.2;

export function boxAreaKm2([west, south, east, north]: readonly number[]): number {
  const midLat = ((south + north) / 2) * (Math.PI / 180);
  return Math.round((east - west) * KM_PER_DEG_LAT * Math.cos(midLat) * (north - south) * KM_PER_DEG_LAT);
}

type DemoTrail = Omit<TrailRisk, "id" | "letter" | "level" | "geom">;

// Real Rainier trails, each marker at a point on its seed line (the midpoint, except Comet Falls,
// moved down the line so it doesn't overlap Van Trump). Riskiest first.
const RAINIER_DEMO_TRAILS: DemoTrail[] = [
  { name: "Kautz Creek Trail", score: 0.74, slopeDeg: 34, primaryFactor: "Drainage channel", center: [-121.8512, 46.7783], zoom: 13.2 },
  { name: "Van Trump Trail", score: 0.66, slopeDeg: 36, primaryFactor: "Steep slopes", center: [-121.7819, 46.7917], zoom: 13.4 },
  { name: "Comet Falls", score: 0.58, slopeDeg: 31, primaryFactor: "Recent rain", center: [-121.7906, 46.7831], zoom: 13.4 },
  { name: "Glacier Basin Trail", score: 0.47, slopeDeg: 29, primaryFactor: "Sparse vegetation", center: [-121.6913, 46.8951], zoom: 13 },
  { name: "Skyline Trail", score: 0.38, slopeDeg: 27, primaryFactor: "Concave hollow", center: [-121.7216, 46.803], zoom: 13.2 },
];

const RAINIER_PREVENTATIVE = [
  "Post a debris-flow advisory at the Kautz Creek and Comet Falls trailheads.",
  "Walk the Van Trump crossings after any 24-hour rain above 1 inch.",
  "Keep culverts on the Glacier Basin Trail clear before the storm.",
  "Stage closure signs at Paradise for the Skyline Trail miles.",
];

export function buildHillView(mountain: MountainDetail): HillView {
  const base = {
    slug: mountain.slug,
    name: mountain.name,
    region: mountain.region,
    isLive: mountain.is_live,
  };
  if (!mountain.is_live) {
    return {
      ...base,
      stats: { elevationM: mountain.elevation_m, meanSlopeDeg: 0, areaKm2: 0 },
      risk: { score: 0, level: mountain.current_risk_level },
      trails: [],
      preventative: [],
      isDemo: false,
      scoreSource: null,
    };
  }
  const byName = new Map(mountain.trails.map((trail) => [trail.name, trail]));
  const trails: TrailRisk[] = [...RAINIER_DEMO_TRAILS]
    .sort((a, b) => b.score - a.score)
    .map((demo, index) => {
      const trail = byName.get(demo.name);
      return {
        ...demo,
        id: trail?.id ?? `demo-${index}`,
        letter: TRAIL_LETTERS[index],
        level: levelForScore(demo.score),
        geom: trail?.geom ?? null,
      };
    });
  const score = 0.52;
  return {
    ...base,
    stats: { elevationM: mountain.elevation_m, meanSlopeDeg: 24, areaKm2: boxAreaKm2(RAINIER_BBOX) },
    risk: { score, level: levelForScore(score) },
    trails,
    preventative: RAINIER_PREVENTATIVE,
    isDemo: true,
    scoreSource: "illustrative",
  };
}
