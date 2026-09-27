import { RISK_COLORS } from "@/lib/theme";

const SIZE = 512;

/** Terrarium elevation tiles, the same ones the map's 3D terrain reads. */
const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const TILE_PX = 256;
/** Tile zoom is picked so the drape spans about this many DEM pixels across. */
const TARGET_DEM_PX = 640;
const ZOOM_RANGE = { min: 9, max: 14 } as const;
const EARTH_CIRCUMFERENCE_M = 40075016.686;

/**
 * Share of the drape in each rank bin before scaling to the peak's overall score. Relative
 * hotspots only; absolute color comes from scaleToOverall().
 */
const BIN_SHARES = [0.12, 0.3, 0.22, 0.36] as const;
const BIN_EDGES = [0, 0.2, 0.45, 0.7, 1] as const;

/** Soft edge (km) on the ground so the drape reads circular, not like a square bbox. */
const RADIAL_FADE_KM = 2.5;
const KM_PER_DEG_LAT = 111.32;
const EARTH_RADIUS_KM = 6371;

/**
 * Same bins as the live probability tiles. Opacity ramps gently at low scores (pale amber);
 * deep red is reserved for 0.7+ after the drape is scaled to the peak's overall model score.
 */
const LEVELS = [
  { min: 0.2, max: 0.45, color: RISK_COLORS.moderate, alpha: 0.46 },
  { min: 0.45, max: 0.7, color: RISK_COLORS.high, alpha: 0.56 },
  { min: 0.7, max: 1, color: RISK_COLORS.extreme, alpha: 0.66 },
] as const;

const LOW_WASH = { floor: 0.03, ceiling: 0.22, alpha: 0.48 } as const;

export interface SyntheticHeatOverlay {
  url: string;
  /** MapLibre image source corners: top-left, top-right, bottom-right, bottom-left. */
  coordinates: [[number, number], [number, number], [number, number], [number, number]];
}

/** Stable 32-bit seed from a peak's identity. The same mountain always draws the same heat. */
function hashSeed(...parts: (string | number)[]): number {
  let h = 2166136261;
  for (const part of parts) {
    const text = String(part);
    for (let i = 0; i < text.length; i += 1) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
  }
  return h >>> 0;
}

/** Seeded uniform draws in [0, 1). Each mountain gets its own sequence. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hexRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

interface NoiseGrid {
  size: number;
  values: Float32Array;
}

function makeGrid(rand: () => number, size: number): NoiseGrid {
  const base = new Float32Array(size * size);
  for (let i = 0; i < base.length; i += 1) {
    base[i] = rand();
  }
  const values = new Float32Array((size + 1) * (size + 1));
  for (let y = 0; y <= size; y += 1) {
    for (let x = 0; x <= size; x += 1) {
      values[y * (size + 1) + x] = base[(y % size) * size + (x % size)];
    }
  }
  return { size, values };
}

/** Smooth value noise. Coordinates wrap so ridges can sit anywhere in the frame. */
function sampleGrid(grid: NoiseGrid, x: number, y: number): number {
  const { size, values } = grid;
  const span = size;
  const fx = ((x % span) + span) % span;
  const fy = ((y % span) + span) % span;
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = (x0 + 1) % (size + 1);
  const y1 = (y0 + 1) % (size + 1);
  const tx = fx - x0;
  const ty = fy - y0;
  const sx = tx * tx * (3 - 2 * tx);
  const sy = ty * ty * (3 - 2 * ty);
  const at = (yy: number, xx: number) => values[yy * (size + 1) + xx];
  const top = at(y0, x0) + (at(y0, x1) - at(y0, x0)) * sx;
  const bottom = at(y1, x0) + (at(y1, x1) - at(y1, x0)) * sx;
  return top + (bottom - top) * sy;
}

interface Octave {
  grid: NoiseGrid;
  freq: number;
  weight: number;
  ox: number;
  oy: number;
  angle: number;
}

/** Seeded grain for the drape, so two places with similar terrain still read differently. */
interface Field {
  octaves: Octave[];
}

function fbm(nx: number, ny: number, octaves: Octave[]): number {
  let noise = 0;
  let weight = 0;
  for (const octave of octaves) {
    const cos = Math.cos(octave.angle);
    const sin = Math.sin(octave.angle);
    const rx = nx * cos - ny * sin;
    const ry = nx * sin + ny * cos;
    noise += octave.weight * sampleGrid(octave.grid, rx * octave.freq + octave.ox, ry * octave.freq + octave.oy);
    weight += octave.weight;
  }
  return noise / weight;
}

/** A different grain for every place: its own scale, rotation, and offsets. */
function buildField(rand: () => number): Field {
  const octaves: Octave[] = [];
  let freq = 1.4 + rand() * 2.2;
  const octaveCount = 4;
  for (let i = 0; i < octaveCount; i += 1) {
    octaves.push({
      grid: makeGrid(rand, 4 + Math.floor(rand() * 5)),
      freq,
      weight: 1 / freq,
      ox: rand() * 40,
      oy: rand() * 40,
      angle: rand() * Math.PI * 2,
    });
    freq *= 1.85 + rand() * 0.5;
  }

  return { octaves };
}

/**
 * Stepped risk colors, matching the live tiles. Only the rise out of low fades alpha, so
 * higher bins stay solid against each other. RGB stays filled at zero alpha so the map's
 * texture filter does not fringe the edge with black.
 */
function colorForScore(score: number): [number, number, number, number] {
  if (score < LOW_WASH.floor) {
    return [0, 0, 0, 0];
  }
  const [r, g, b] = hexRgb(RISK_COLORS.moderate);
  if (score < LOW_WASH.ceiling) {
    const t = smoothstep(LOW_WASH.floor, LOW_WASH.ceiling, score);
    return [r, g, b, Math.round(LOW_WASH.alpha * t * 255)];
  }
  const level = LEVELS.find((entry) => score < entry.max) ?? LEVELS[LEVELS.length - 1];
  const [lr, lg, lb] = hexRgb(level.color);
  const enter = level === LEVELS[0] ? smoothstep(level.min, level.min + 0.05, score) : 1;
  return [lr, lg, lb, Math.round(level.alpha * enter * 255)];
}

/** Worst-pixel cap from the card score: readable on low peaks, still no blanket extreme red. */
function visualPeak(anchor: number): number {
  const boosted = anchor * 1.65 + 0.09;
  if (anchor < 0.2) {
    return Math.min(0.34, Math.max(anchor, boosted));
  }
  if (anchor < 0.45) {
    return Math.min(0.55, boosted);
  }
  return Math.min(0.88, boosted);
}

/**
 * Rank scores show relative hotspots; visualPeak() ties them to overall risk but leaves headroom
 * so a 0.11 summit still reads as light–moderate on the map, not invisible or all crimson.
 */
function scaleToOverall(ranked: Float32Array, overall: number | null): Float32Array {
  const anchor = Math.max(0.05, Math.min(0.95, overall ?? 0.12));
  const peak = visualPeak(anchor);
  const out = new Float32Array(ranked.length);
  const floor = peak * 0.08;
  const span = peak - floor;
  for (let i = 0; i < ranked.length; i += 1) {
    out[i] = floor + span * ranked[i];
  }
  return out;
}

interface ElevationGrid {
  width: number;
  height: number;
  /** Meters, row-major, in Web Mercator pixels at `zoom`. */
  elevation: Float32Array;
  zoom: number;
  /** Mercator pixel of the grid's top-left corner at `zoom`. */
  originX: number;
  originY: number;
  /** Ground meters per DEM pixel at the drape's latitude. */
  cellM: number;
}

function mercatorX(lon: number, zoom: number): number {
  return ((lon + 180) / 360) * TILE_PX * 2 ** zoom;
}

function mercatorY(lat: number, zoom: number): number {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * TILE_PX * 2 ** zoom;
}

async function loadTile(z: number, x: number, y: number): Promise<ImageBitmap> {
  const url = TERRAIN_TILES.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`terrain tile ${z}/${x}/${y}: ${response.status}`);
  }
  return createImageBitmap(await response.blob());
}

/** Fetch and decode the Terrarium tiles under the bounds into one elevation grid. */
async function loadElevation(bounds: [number, number, number, number]): Promise<ElevationGrid> {
  const [west, south, east, north] = bounds;
  const spanAtZero = mercatorX(east, 0) - mercatorX(west, 0);
  const zoom = Math.max(ZOOM_RANGE.min, Math.min(ZOOM_RANGE.max, Math.round(Math.log2(TARGET_DEM_PX / spanAtZero))));
  const tx0 = Math.floor(mercatorX(west, zoom) / TILE_PX);
  const tx1 = Math.floor(mercatorX(east, zoom) / TILE_PX);
  const ty0 = Math.floor(mercatorY(north, zoom) / TILE_PX);
  const ty1 = Math.floor(mercatorY(south, zoom) / TILE_PX);
  const width = (tx1 - tx0 + 1) * TILE_PX;
  const height = (ty1 - ty0 + 1) * TILE_PX;

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) {
    throw new Error("no 2d context");
  }
  const jobs: Promise<void>[] = [];
  for (let ty = ty0; ty <= ty1; ty += 1) {
    for (let tx = tx0; tx <= tx1; tx += 1) {
      jobs.push(
        loadTile(zoom, tx, ty).then((bitmap) => {
          ctx.drawImage(bitmap, (tx - tx0) * TILE_PX, (ty - ty0) * TILE_PX);
          bitmap.close();
        }),
      );
    }
  }
  await Promise.all(jobs);

  const pixels = ctx.getImageData(0, 0, width, height).data;
  const elevation = new Float32Array(width * height);
  for (let i = 0; i < elevation.length; i += 1) {
    elevation[i] = pixels[i * 4] * 256 + pixels[i * 4 + 1] + pixels[i * 4 + 2] / 256 - 32768;
  }
  const lat = (north + south) / 2;
  return {
    width,
    height,
    elevation,
    zoom,
    originX: tx0 * TILE_PX,
    originY: ty0 * TILE_PX,
    cellM: (EARTH_CIRCUMFERENCE_M * Math.cos((lat * Math.PI) / 180)) / (TILE_PX * 2 ** zoom),
  };
}

interface TerrainFields {
  slopeDeg: Float32Array;
  /** Positive in gullies and hollows, where debris gathers; negative on ridges. */
  hollow: Float32Array;
}

/** Slope and hollowness at every DEM pixel. */
function terrainFields(grid: ElevationGrid): TerrainFields {
  const { width, height, elevation, cellM } = grid;
  const slopeDeg = new Float32Array(width * height);
  const hollow = new Float32Array(width * height);
  const at = (x: number, y: number) =>
    elevation[Math.min(height - 1, Math.max(0, y)) * width + Math.min(width - 1, Math.max(0, x))];
  // Hollows are read over a wider window than slope, so whole gullies light up, not single pixels.
  const reach = 4;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = (at(x + 1, y) - at(x - 1, y)) / (2 * cellM);
      const dy = (at(x, y + 1) - at(x, y - 1)) / (2 * cellM);
      slopeDeg[y * width + x] = (Math.atan(Math.hypot(dx, dy)) * 180) / Math.PI;
      const around = at(x - reach, y) + at(x + reach, y) + at(x, y - reach) + at(x, y + reach);
      hollow[y * width + x] = Math.tanh((around / 4 - at(x, y)) / 25);
    }
  }
  return { slopeDeg, hollow };
}

function bilinear(values: Float32Array, width: number, height: number, x: number, y: number): number {
  const cx = Math.min(width - 1.001, Math.max(0, x));
  const cy = Math.min(height - 1.001, Math.max(0, y));
  const x0 = Math.floor(cx);
  const y0 = Math.floor(cy);
  const tx = cx - x0;
  const ty = cy - y0;
  const i = y0 * width + x0;
  const top = values[i] + (values[i + 1] - values[i]) * tx;
  const bottom = values[i + width] + (values[i + width + 1] - values[i + width]) * tx;
  return top + (bottom - top) * ty;
}

function quantile(sorted: Float32Array, q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))))];
}

function distanceKm(centerLon: number, centerLat: number, lon: number, lat: number): number {
  const clat = (centerLat * Math.PI) / 180;
  const latR = (lat * Math.PI) / 180;
  const dLat = ((lat - centerLat) * Math.PI) / 180;
  const dLon = ((lon - centerLon) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(clat) * Math.cos(latR) * Math.sin(dLon / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.asin(Math.sqrt(a));
}

/** 0–1 mask: full inside a circle inscribed in the bounds, feathered at the rim. */
function radialGroundMask(bounds: [number, number, number, number], lon: number, lat: number): number {
  const [west, south, east, north] = bounds;
  const centerLon = (west + east) / 2;
  const centerLat = (south + north) / 2;
  const kmPerDegLon = KM_PER_DEG_LAT * Math.cos((centerLat * Math.PI) / 180);
  const halfEw = ((east - west) * kmPerDegLon) / 2;
  const halfNs = ((north - south) * KM_PER_DEG_LAT) / 2;
  const radiusKm = Math.min(halfEw, halfNs);
  const fadeKm = Math.max(RADIAL_FADE_KM, radiusKm * 0.08);
  const dist = distanceKm(centerLon, centerLat, lon, lat);
  if (dist >= radiusKm) {
    return 0;
  }
  if (dist <= radiusKm - fadeKm) {
    return 1;
  }
  return (radiusKm - dist) / fadeKm;
}

/**
 * Raw susceptibility from the terrain: steep ground first (failures peak around 35-45 degrees and
 * ease off on bare cliffs), then height up the mountain, then gullies, with seeded noise for grain.
 */
function rawScores(
  grid: ElevationGrid | null,
  bounds: [number, number, number, number],
  field: Field,
): Float32Array {
  const [west, south, east, north] = bounds;
  const raw = new Float32Array(SIZE * SIZE);
  if (!grid) {
    for (let y = 0; y < SIZE; y += 1) {
      for (let x = 0; x < SIZE; x += 1) {
        raw[y * SIZE + x] = fbm((x / (SIZE - 1)) * 2 - 1, (y / (SIZE - 1)) * 2 - 1, field.octaves);
      }
    }
    return raw;
  }

  const { slopeDeg, hollow } = terrainFields(grid);
  const x0 = mercatorX(west, grid.zoom) - grid.originX;
  const x1 = mercatorX(east, grid.zoom) - grid.originX;
  const y0 = mercatorY(north, grid.zoom) - grid.originY;
  const y1 = mercatorY(south, grid.zoom) - grid.originY;

  const sampled = new Float32Array(SIZE * SIZE);
  for (let y = 0; y < SIZE; y += 1) {
    const gy = y0 + (y / (SIZE - 1)) * (y1 - y0);
    for (let x = 0; x < SIZE; x += 1) {
      sampled[y * SIZE + x] = bilinear(grid.elevation, grid.width, grid.height, x0 + (x / (SIZE - 1)) * (x1 - x0), gy);
    }
  }
  const sortedElevation = sampled.slice().sort();
  const low = quantile(sortedElevation, 0.05);
  const high = Math.max(low + 1, quantile(sortedElevation, 0.99));

  for (let y = 0; y < SIZE; y += 1) {
    const gy = y0 + (y / (SIZE - 1)) * (y1 - y0);
    const ny = (y / (SIZE - 1)) * 2 - 1;
    for (let x = 0; x < SIZE; x += 1) {
      const gx = x0 + (x / (SIZE - 1)) * (x1 - x0);
      const nx = (x / (SIZE - 1)) * 2 - 1;
      const slope = bilinear(slopeDeg, grid.width, grid.height, gx, gy);
      const steep = smoothstep(8, 38, slope) * (1 - 0.22 * smoothstep(52, 72, slope));
      const height = Math.max(0, Math.min(1, (sampled[y * SIZE + x] - low) / (high - low)));
      const heightTerm = height * (0.7 + 0.3 * height);
      const gully = Math.max(0, bilinear(hollow, grid.width, grid.height, gx, gy));
      const grain = fbm(nx * 2.5, ny * 2.5, field.octaves) - 0.5;
      raw[y * SIZE + x] = 0.48 * steep + 0.3 * heightTerm + 0.14 * gully + 0.32 * grain;
    }
  }
  return raw;
}

/** Rank each pixel against the whole drape, then place it in its bin by BIN_SHARES. */
function scoresFromRanks(raw: Float32Array): Float32Array {
  const order = new Uint32Array(raw.length);
  for (let i = 0; i < order.length; i += 1) {
    order[i] = i;
  }
  order.sort((a, b) => raw[a] - raw[b]);
  const scores = new Float32Array(raw.length);
  for (let rank = 0; rank < order.length; rank += 1) {
    let pct = rank / (order.length - 1);
    let bin = 0;
    while (bin < BIN_SHARES.length - 1 && pct > BIN_SHARES[bin]) {
      pct -= BIN_SHARES[bin];
      bin += 1;
    }
    const within = Math.min(1, pct / BIN_SHARES[bin]);
    scores[order[rank]] = BIN_EDGES[bin] + within * (BIN_EDGES[bin + 1] - BIN_EDGES[bin]);
  }
  return scores;
}

/**
 * A probability-style drape for places that have no rendered tiles, drawn from the real terrain:
 * the elevation tiles under the bounds give slope, height, and gullies, so the heat follows the
 * flanks and drainages the way the Rainier tiles do. Colors and opacities match the Rainier heat
 * map. The grain is seeded from the slug, so each place is stable across reloads. If the
 * elevation tiles fail to load, the drape falls back to the seeded noise alone.
 */
export async function buildSyntheticHeatOverlay(
  slug: string,
  lon: number,
  lat: number,
  bounds: [number, number, number, number],
  /** Summit model probability from GET /mountains/{slug}; anchors the drape to the overall risk card. */
  overallScore: number | null = null,
): Promise<SyntheticHeatOverlay> {
  const [west, south, east, north] = bounds;
  const coordinates: SyntheticHeatOverlay["coordinates"] = [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
  ];
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return { url: "", coordinates };
  }

  const grid = await loadElevation(bounds).catch(() => null);
  const field = buildField(mulberry32(hashSeed(slug, lon.toFixed(4), lat.toFixed(4))));
  const scores = scaleToOverall(scoresFromRanks(rawScores(grid, bounds, field)), overallScore);
  const image = ctx.createImageData(SIZE, SIZE);
  for (let y = 0; y < SIZE; y += 1) {
    const pxLat = north - (y / (SIZE - 1)) * (north - south);
    for (let x = 0; x < SIZE; x += 1) {
      const pxLon = west + (x / (SIZE - 1)) * (east - west);
      const mask = radialGroundMask(bounds, pxLon, pxLat);
      const i = (y * SIZE + x) * 4;
      if (mask <= 0.01) {
        image.data[i + 3] = 0;
        continue;
      }
      const [r, g, b, a] = colorForScore(scores[y * SIZE + x]);
      image.data[i] = r;
      image.data[i + 1] = g;
      image.data[i + 2] = b;
      image.data[i + 3] = Math.round(a * mask);
    }
  }
  ctx.putImageData(image, 0, 0);
  return { url: canvas.toDataURL("image/png"), coordinates };
}
