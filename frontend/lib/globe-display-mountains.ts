import type { Mountain } from "@/lib/types";

/**
 * Max markers on the home globe. Set in the repo root `.env` as
 * `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT`. `0` or invalid values show every peak.
 * Default 50 when the variable is missing.
 */
export function globeMountainLimit(): number {
  const raw = process.env.NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT?.trim();
  if (raw === undefined || raw === "") {
    return 50;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return parsed;
}

type RegionId = "americas" | "europeAfrica" | "asiaPacific";

const REGIONS: { id: RegionId; match: (m: Mountain) => boolean }[] = [
  { id: "americas", match: (m) => m.lon <= -30 },
  { id: "europeAfrica", match: (m) => m.lon > -30 && m.lon <= 60 },
  { id: "asiaPacific", match: (m) => m.lon > 60 },
];

function isPolar(m: Mountain): boolean {
  return Math.abs(m.lat) >= 58;
}

/** Prefer settled latitudes so the globe is not all Antarctica or Arctic. */
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

function cellIndex(value: number, min: number, span: number, buckets: number): number {
  const t = (value - min) / span;
  const clamped = Math.min(1, Math.max(0, t));
  return Math.min(buckets - 1, Math.floor(clamped * buckets));
}

function pickSpacedFromPool(pool: Mountain[], quota: number, polarCap: number): Mountain[] {
  if (quota <= 0 || pool.length === 0) {
    return [];
  }

  const nLat = Math.max(3, Math.round(Math.sqrt(quota)));
  const nLon = Math.max(4, Math.ceil(quota / nLat));
  const buckets = new Map<string, Mountain[]>();

  for (const mountain of pool) {
    const latIdx = cellIndex(mountain.lat, -90, 180, nLat);
    const lonIdx = cellIndex(mountain.lon, -180, 360, nLon);
    const key = `${latIdx}:${lonIdx}`;
    const list = buckets.get(key);
    if (list) {
      list.push(mountain);
    } else {
      buckets.set(key, [mountain]);
    }
  }

  for (const list of buckets.values()) {
    list.sort(sortCandidates);
  }

  const keys = [...buckets.keys()].sort();
  const picked: Mountain[] = [];
  let polarUsed = 0;
  let round = 0;

  while (picked.length < quota && keys.length > 0) {
    let added = false;
    for (const key of keys) {
      const list = buckets.get(key)!;
      if (round >= list.length) {
        continue;
      }
      const candidate = list[round]!;
      if (isPolar(candidate) && polarUsed >= polarCap) {
        continue;
      }
      picked.push(candidate);
      if (isPolar(candidate)) {
        polarUsed += 1;
      }
      added = true;
      if (picked.length >= quota) {
        break;
      }
    }
    if (!added) {
      break;
    }
    round += 1;
  }

  if (picked.length < quota) {
    for (const mountain of [...pool].sort(sortCandidates)) {
      if (picked.some((p) => p.slug === mountain.slug)) {
        continue;
      }
      if (isPolar(mountain) && polarUsed >= polarCap) {
        continue;
      }
      picked.push(mountain);
      if (isPolar(mountain)) {
        polarUsed += 1;
      }
      if (picked.length >= quota) {
        break;
      }
    }
  }

  return picked;
}

function pickRegionalCatalog(catalog: Mountain[], budget: number): Mountain[] {
  const polarCap = Math.max(2, Math.floor(budget * 0.12));
  const perRegion = Math.max(1, Math.floor(budget / REGIONS.length));
  const picked: Mountain[] = [];
  const used = new Set<string>();

  for (const region of REGIONS) {
    const pool = catalog.filter((m) => region.match(m)).sort(sortCandidates);
    for (const mountain of pickSpacedFromPool(pool, perRegion, polarCap)) {
      if (used.has(mountain.slug)) {
        continue;
      }
      used.add(mountain.slug);
      picked.push(mountain);
    }
  }

  if (picked.length < budget) {
    const rest = catalog.filter((m) => !used.has(m.slug)).sort(sortCandidates);
    for (const mountain of pickSpacedFromPool(rest, budget - picked.length, polarCap)) {
      if (used.has(mountain.slug)) {
        continue;
      }
      used.add(mountain.slug);
      picked.push(mountain);
    }
  }

  return picked.slice(0, budget);
}

/**
 * Order for the search dropdown (empty query): live first, then interleaved regions.
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

/**
 * Pick up to `limit` mountains for the globe with continental spread and few polar pins.
 * Live peaks always show. Catalog mountains fill most of the budget. Hills are capped so
 * sub-3k reclassification does not crowd out major summits. Search still uses the full list.
 */
export function selectGlobeMountains(mountains: Mountain[], limit: number): Mountain[] {
  if (limit <= 0 || mountains.length <= limit) {
    return orderMountainsForBrowse(mountains);
  }

  const live = mountains.filter((m) => m.is_live);
  const hills = mountains.filter((m) => !m.is_live && m.kind === "hill");
  const catalog = mountains.filter((m) => !m.is_live && m.kind !== "hill");
  const hillCap = Math.min(hills.length, Math.max(6, Math.round(limit * 0.15)));

  const picked: Mountain[] = [];
  const used = new Set<string>();
  const take = (list: Mountain[]) => {
    for (const mountain of list) {
      if (picked.length >= limit) {
        break;
      }
      if (used.has(mountain.slug)) {
        continue;
      }
      used.add(mountain.slug);
      picked.push(mountain);
    }
  };

  take(live);
  take(pickRegionalCatalog(catalog, Math.max(0, limit - picked.length - hillCap)));
  take(pickRegionalCatalog(hills, Math.max(0, limit - picked.length)));

  if (picked.length < limit) {
    const rest = mountains.filter((m) => !used.has(m.slug));
    take(pickRegionalCatalog(rest, limit - picked.length));
  }

  return picked;
}
