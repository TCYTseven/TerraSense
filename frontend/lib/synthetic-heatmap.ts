import { RISK_COLORS } from "@/lib/theme";

const SIZE = 512;

/**
 * Same bins and opacities as the Rainier probability tiles: low is clear so terrain shows
 * through, and the worst ground is the most opaque.
 */
const LEVELS = [
  { min: 0.2, max: 0.45, color: RISK_COLORS.moderate, alpha: 0.4 },
  { min: 0.45, max: 0.7, color: RISK_COLORS.high, alpha: 0.55 },
  { min: 0.7, max: 1, color: RISK_COLORS.extreme, alpha: 0.7 },
] as const;

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

interface Hotspot {
  x: number;
  y: number;
  sigma: number;
  amp: number;
}

interface Field {
  octaves: Octave[];
  spots: Hotspot[];
  /** Where the blanket sits on the risk ramp before the ridges and cores push it around. */
  cover: number;
  /** How far the noise swings the level, so some peaks are mottled and some are smoother. */
  contrast: number;
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

/**
 * A different blanket for every peak: its own ridge scale, rotation, coverage, and
 * hotspot placement. The summit stays warm; the pattern around it does not repeat.
 */
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

  const spots: Hotspot[] = [
    {
      x: (rand() - 0.5) * 0.35,
      y: (rand() - 0.5) * 0.35,
      sigma: 0.22 + rand() * 0.2,
      amp: 0.55 + rand() * 0.45,
    },
  ];
  const extra = 2 + Math.floor(rand() * 4);
  for (let i = 0; i < extra; i += 1) {
    spots.push({
      x: (rand() - 0.5) * 1.4,
      y: (rand() - 0.5) * 1.1,
      sigma: 0.1 + rand() * 0.22,
      amp: 0.25 + rand() * 0.7,
    });
  }

  return {
    octaves,
    spots,
    cover: 0.42 + rand() * 0.28,
    contrast: 0.28 + rand() * 0.34,
  };
}

function scoreAt(nx: number, ny: number, field: Field): number {
  const warpX = fbm(nx * 0.65 + 3.1, ny * 0.65 - 1.7, field.octaves);
  const warpY = fbm(nx * 0.65 - 2.4, ny * 0.65 + 4.2, field.octaves);
  const wx = nx + (warpX - 0.5) * 0.5;
  const wy = ny + (warpY - 0.5) * 0.5;
  const noise = fbm(wx, wy, field.octaves);

  let hot = 0;
  for (const spot of field.spots) {
    const distance = Math.hypot(nx - spot.x, ny - spot.y);
    hot += spot.amp * Math.exp(-(distance * distance) / (2 * spot.sigma * spot.sigma));
  }

  const score = field.cover + (noise - 0.5) * field.contrast + Math.min(hot, 1.2) * 0.34;
  return Math.max(0, Math.min(1, score));
}

/**
 * Stepped risk colors, matching the live tiles. Only the rise out of low fades alpha, so
 * higher bins stay solid against each other. RGB stays filled at zero alpha so the map's
 * texture filter does not fringe the edge with black.
 */
function colorForScore(score: number): [number, number, number, number] {
  const level = LEVELS.find((entry) => score < entry.max) ?? LEVELS[LEVELS.length - 1];
  const [r, g, b] = hexRgb(level.color);
  if (score < LEVELS[0].min) {
    return [r, g, b, 0];
  }
  const enter = level === LEVELS[0] ? smoothstep(level.min, level.min + 0.04, score) : 1;
  return [r, g, b, Math.round(level.alpha * enter * 255)];
}

/**
 * Dissolves the drape into the terrain. Sides and the north edge fade over a short band.
 * The south edge fades across a much longer one: that is the cut that reads as a rectangle
 * laid on the lower slopes.
 */
function edgeMask(u: number, v: number): number {
  const sides = Math.min(smoothstep(0, 0.14, u), smoothstep(0, 0.14, 1 - u));
  const top = smoothstep(0, 0.12, v);
  const bottom = 1 - smoothstep(0.62, 1, v);
  const radius = Math.hypot((u - 0.5) * 2, (v - 0.42) * 2);
  const round = 1 - smoothstep(0.95, 1.35, radius);
  return sides * top * bottom * round;
}

/**
 * A probability-style drape for peaks that have no local tiles. Colors and opacities match
 * the Rainier heat map. The pattern is seeded from the slug, so each mountain is different
 * and stable across reloads.
 */
export function buildSyntheticHeatOverlay(
  slug: string,
  lon: number,
  lat: number,
  bounds: [number, number, number, number],
): SyntheticHeatOverlay {
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

  const field = buildField(mulberry32(hashSeed(slug, lon.toFixed(4), lat.toFixed(4))));
  const image = ctx.createImageData(SIZE, SIZE);
  for (let y = 0; y < SIZE; y += 1) {
    const v = y / (SIZE - 1);
    const ny = v * 2 - 1;
    for (let x = 0; x < SIZE; x += 1) {
      const u = x / (SIZE - 1);
      const nx = u * 2 - 1;
      const [r, g, b, a] = colorForScore(scoreAt(nx, ny, field));
      const i = (y * SIZE + x) * 4;
      image.data[i] = r;
      image.data[i + 1] = g;
      image.data[i + 2] = b;
      image.data[i + 3] = Math.round(a * edgeMask(u, v));
    }
  }
  ctx.putImageData(image, 0, 0);
  return { url: canvas.toDataURL("image/png"), coordinates };
}
