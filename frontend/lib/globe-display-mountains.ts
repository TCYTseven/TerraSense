import type { Mountain } from "@/lib/types";

type RegionId = "americas" | "europeAfrica" | "asiaPacific";

const REGIONS: { id: RegionId; match: (m: Mountain) => boolean }[] = [
  { id: "americas", match: (m) => m.lon <= -30 },
  { id: "europeAfrica", match: (m) => m.lon > -30 && m.lon <= 60 },
  { id: "asiaPacific", match: (m) => m.lon > 60 },
];

/** Prefer settled latitudes so browse order is not all Antarctica or Arctic. */
function browseScore(m: Mountain): number {
  const lat = Math.abs(m.lat);
  if (lat >= 58) {
    return 0;
  }
  if (lat >= 15 && lat <= 55) {
    return 3;
  }
  if (lat >= 5 && lat < 15) {
    return 2;
  }
  return 1;
}

function sortCandidates(a: Mountain, b: Mountain): number {
  const score = browseScore(b) - browseScore(a);
  if (score !== 0) {
    return score;
  }
  if (b.elevation_m !== a.elevation_m) {
    return b.elevation_m - a.elevation_m;
  }
  return a.name.localeCompare(b.name);
}

/**
 * Order for search (empty query) and globe markers: live first, then interleaved regions.
 */
export function orderMountainsForBrowse(mountains: Mountain[]): Mountain[] {
  const live = mountains.filter((m) => m.is_live);
  const catalog = mountains.filter((m) => !m.is_live);
  const byRegion = REGIONS.map((region) =>
    catalog.filter((m) => region.match(m)).sort(sortCandidates),
  );
  const interleaved: Mountain[] = [];
  let round = 0;
  while (interleaved.length < catalog.length) {
    let added = false;
    for (const list of byRegion) {
      if (round < list.length) {
        interleaved.push(list[round]!);
        added = true;
      }
    }
    if (!added) {
      break;
    }
    round += 1;
  }
  return [...live, ...interleaved];
}

const GLOBE_MARKER_FRACTION = 0.75;

/**
 * Up to 75% of catalog peaks on the globe, keeping every mapped-route mountain first so
 * clutter drops without hiding Rainier and the demo packs.
 */
export function selectGlobeMountains(mountains: Mountain[]): Mountain[] {
  if (mountains.length === 0) {
    return [];
  }
  const target = Math.max(1, Math.round(mountains.length * GLOBE_MARKER_FRACTION));
  const ordered = orderMountainsForBrowse(mountains);
  const withRoutes = ordered.filter((m) => m.trail_count > 0);
  const withoutRoutes = ordered.filter((m) => m.trail_count === 0);
  const picked: Mountain[] = [];
  for (const mountain of withRoutes) {
    if (picked.length >= target) {
      break;
    }
    picked.push(mountain);
  }
  for (const mountain of withoutRoutes) {
    if (picked.length >= target) {
      break;
    }
    picked.push(mountain);
  }
  return picked;
}
