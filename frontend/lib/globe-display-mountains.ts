import type { Mountain } from "@/lib/types";

/**
 * Max markers on the home globe. Set in the repo root `.env` as
 * `NEXT_PUBLIC_GLOBE_MOUNTAIN_LIMIT`. `0` or unset invalid values show every peak.
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

function cellIndex(value: number, min: number, span: number, buckets: number): number {
  const t = (value - min) / span;
  const clamped = Math.min(1, Math.max(0, t));
  return Math.min(buckets - 1, Math.floor(clamped * buckets));
}

/**
 * Pick up to `limit` mountains for the globe with even geographic spread.
 * Live mountains are always included. Search still uses the full API list.
 */
export function selectGlobeMountains(mountains: Mountain[], limit: number): Mountain[] {
  if (limit <= 0 || mountains.length <= limit) {
    return [...mountains].sort(sortLiveFirst);
  }

  const live = mountains.filter((m) => m.is_live);
  const catalog = mountains.filter((m) => !m.is_live);
  let budget = limit - live.length;
  if (budget <= 0) {
    return live.slice(0, limit).sort(sortLiveFirst);
  }

  const nLat = Math.max(5, Math.round(Math.sqrt(budget)));
  const nLon = Math.max(6, Math.ceil(budget / nLat));

  const buckets = new Map<string, Mountain[]>();
  for (const mountain of catalog) {
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
    list.sort((a, b) => b.elevation_m - a.elevation_m || a.name.localeCompare(b.name));
  }

  const keys = [...buckets.keys()].sort();
  const picked: Mountain[] = [];
  let round = 0;
  while (picked.length < budget && keys.length > 0) {
    let added = false;
    for (const key of keys) {
      const list = buckets.get(key)!;
      if (round < list.length) {
        picked.push(list[round]!);
        added = true;
        if (picked.length >= budget) {
          break;
        }
      }
    }
    if (!added) {
      break;
    }
    round += 1;
  }

  return [...live, ...picked].sort(sortLiveFirst);
}

function sortLiveFirst(a: Mountain, b: Mountain): number {
  if (a.is_live !== b.is_live) {
    return a.is_live ? -1 : 1;
  }
  return a.name.localeCompare(b.name);
}
