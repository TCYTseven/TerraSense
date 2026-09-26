import { displayRiskLevel } from "./format";
import { TRAIL_LETTERS, type HillView, type TrailRisk } from "./hill";
import type { MountainDetail, MountainRiskSummary } from "./types";

const KM_PER_DEG_LAT = 111.2;
const TRAIL_ZOOM = 13.3;

function boxAreaKm2([west, south, east, north]: readonly number[]): number {
  const midLat = ((south + north) / 2) * (Math.PI / 180);
  return Math.round((east - west) * KM_PER_DEG_LAT * Math.cos(midLat) * (north - south) * KM_PER_DEG_LAT);
}

function preventative(summary: MountainRiskSummary, trails: TrailRisk[]): string[] {
  const [worst] = trails;
  if (!worst) return [];
  const items: string[] = [];
  const where = [worst.slopeDeg !== null ? `${worst.slopeDeg}°` : null, worst.primaryFactor?.toLowerCase()]
    .filter(Boolean)
    .join(" ");
  items.push(
    `Walk ${worst.name} at its worst point${where ? ` (${where})` : ""} after any 72-hour rain above ${summary.threshold_72h_mm} mm.`,
  );
  const severe = trails.filter((t) => t.level === "high" || t.level === "extreme");
  items.push(
    severe.length > 0
      ? `Stage closure signs for ${severe.map((t) => t.name).join(", ")}: the current map puts them at high or above.`
      : "No mapped trail reaches high on the current map. Run Analyze now again when the forecast changes.",
  );
  const channels = trails.filter((t) => t.primaryFactor === "Drainage channel");
  if (channels.length > 0) {
    items.push(`Keep culverts and creek crossings clear on ${channels.map((t) => t.name).join(", ")}.`);
  }
  return items;
}

/**
 * The hill card's view model from the mountain and the risk summary. Every score, slope, and
 * factor comes from the saved 72-hour map the heat layer shows. Before the first save there is
 * no summary, so the card shows no scores rather than made-up ones.
 */
export function buildHillView(mountain: MountainDetail, summary: MountainRiskSummary | null): HillView {
  const base = { slug: mountain.slug, name: mountain.name, region: mountain.region, isLive: mountain.is_live };
  if (!mountain.is_live || summary === null) {
    // A static mountain shows the model's live summit prediction, not the seeded catalog
    // color: the score is the regional model's calibrated probability when it has one.
    return {
      ...base,
      stats: { elevationM: mountain.elevation_m, meanSlopeDeg: null, areaKm2: null },
      risk: { score: mountain.model_probability ?? null, level: displayRiskLevel(mountain) },
      trails: [],
      preventative: [],
      scoring: null,
    };
  }
  const geomById = new Map(mountain.trails.map((trail) => [trail.id, trail.geom]));
  const trails: TrailRisk[] = summary.trails.slice(0, TRAIL_LETTERS.length).map((scored, index) => {
    const geom = geomById.get(scored.trail_id) ?? null;
    const center = scored.worst_point ?? geom?.coordinates[Math.floor(geom.coordinates.length / 2)] ?? [mountain.lon, mountain.lat];
    return {
      id: scored.trail_id,
      letter: TRAIL_LETTERS[index],
      name: scored.name,
      score: scored.max_probability,
      level: scored.level,
      slopeDeg: scored.slope_deg,
      primaryFactor: scored.factor,
      center,
      zoom: TRAIL_ZOOM,
      geom,
    };
  });
  return {
    ...base,
    stats: {
      elevationM: mountain.elevation_m,
      meanSlopeDeg: summary.mean_slope_deg,
      areaKm2: summary.bbox ? boxAreaKm2(summary.bbox) : null,
    },
    risk: { score: summary.overall.score, level: summary.overall.level },
    trails,
    preventative: preventative(summary, trails),
    scoring: {
      scoredAt: summary.scored_at,
      method: summary.method,
      trailsScored: summary.overall.trails_scored,
      shareAreaHigh: summary.overall.share_area_high,
    },
  };
}
