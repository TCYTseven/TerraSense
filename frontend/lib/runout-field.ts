import { FLOW_COLORS } from "./theme";
import type { Position, RunoutField } from "./types";

/** One flat-colored triangle, or the clipped part of one, per feature. */
export type MeshFeatureCollection = GeoJSON.FeatureCollection<GeoJSON.Polygon, { color: string }>;

/**
 * Where playback is in simulated time. The map reads it every animation frame, so the
 * front moves continuously instead of stepping between frames.
 */
export interface Playhead {
  /** performance.now() when simulated time was 0. */
  t0: number;
  /** Wall milliseconds per simulated second. */
  msPerS: number;
  durationS: number;
}

export function playheadTime(playhead: Playhead, now: number): number {
  return Math.min(playhead.durationS, Math.max(0, (now - playhead.t0) / playhead.msPerS));
}

const NEVER = 65535;
/**
 * The mesh has at most this many vertices along its longer side. One vertex per model
 * cell (about 26 m) on a typical flow; a larger flow is strided so the triangle count stays
 * low enough to rebuild every redraw.
 */
const MAX_MESH_SIDE = 64;
/** Fresh debris at the snout is darker and wetter than what has settled behind it. */
const SNOUT: RGB = [52, 30, 14];
const SNOUT_MIX = 0.45;

type RGB = [number, number, number];

function hexRgb(hex: string): RGB {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function css([r, g, b]: RGB): string {
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

// FLOW_COLORS runs dark core first, so depth 1 is index 0. Each triangle takes one flat tone.
const TONES = FLOW_COLORS.map(hexRgb);
const TONE_CSS = TONES.map(css);
const SNOUT_CSS = TONES.map((tone) => css(tone.map((c, i) => c + (SNOUT[i] - c) * SNOUT_MIX) as RGB));

function decode(base64: string): Uint8Array {
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    out[i] = raw.charCodeAt(i);
  }
  return out;
}

const WORLD = 2 * Math.PI * 6378137;

function toMercator([lon, lat]: Position): Position {
  const x = (lon / 360) * WORLD;
  const y = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) * 6378137;
  return [x, y];
}

function toLonLat([x, y]: Position): Position {
  return [(x / WORLD) * 360, ((2 * Math.atan(Math.exp(y / 6378137)) - Math.PI / 2) * 180) / Math.PI];
}

/**
 * The runout as a triangle mesh. Every grid cell is two triangles, each filled with one
 * flat tone. Triangles on the flow's edge and at the moving front are clipped along the
 * contour, so the outline is faceted but never stair-stepped, and the front sweeps
 * continuously. The map draws the result as ordinary polygons.
 */
export class RunoutMesh {
  private readonly cols: number;
  private readonly rows: number;
  private readonly lonlat: Position[];
  private readonly cover: Float32Array;
  private readonly arrival: Float32Array;
  private readonly depth: Float32Array;
  /** Triangles as vertex index triples, earliest possible arrival first. */
  private readonly triangles: Int32Array;
  private readonly earliest: Float32Array;
  private readonly soft: number;

  constructor(field: RunoutField, durationS: number) {
    const { width, height } = field;
    const stride = Math.max(1, Math.ceil(Math.max(width, height) / MAX_MESH_SIDE));
    const cols = Math.ceil(width / stride);
    const rows = Math.ceil(height / stride);
    this.cols = cols;
    this.rows = rows;
    this.soft = Math.max(2, durationS * 0.035);

    const coverSrc = decode(field.cover);
    const depthSrc = decode(field.depth);
    const arrivalBytes = decode(field.arrival);
    // Little-endian on the wire and in every browser we target.
    const arrivalSrc = new Uint16Array(arrivalBytes.buffer, arrivalBytes.byteOffset, width * height);

    const [tl, tr, br, bl] = field.corners.map(toMercator);
    this.lonlat = [];
    this.cover = new Float32Array(cols * rows);
    this.arrival = new Float32Array(cols * rows);
    this.depth = new Float32Array(cols * rows);
    for (let r = 0; r < rows; r += 1) {
      const srcRow = Math.min(height - 1, r * stride + Math.floor(stride / 2));
      const v = (srcRow + 0.5) / height;
      for (let c = 0; c < cols; c += 1) {
        const srcCol = Math.min(width - 1, c * stride + Math.floor(stride / 2));
        const u = (srcCol + 0.5) / width;
        // Vertices sit at cell centres, placed bilinearly between the four Mercator corners.
        const x = (1 - v) * ((1 - u) * tl[0] + u * tr[0]) + v * ((1 - u) * bl[0] + u * br[0]);
        const y = (1 - v) * ((1 - u) * tl[1] + u * tr[1]) + v * ((1 - u) * bl[1] + u * br[1]);
        this.lonlat.push(toLonLat([x, y]));
        const i = r * cols + c;
        const src = srcRow * width + srcCol;
        this.cover[i] = coverSrc[src] / 255;
        this.depth[i] = depthSrc[src] / 255;
        const a = arrivalSrc[src];
        this.arrival[i] = a === NEVER ? Number.POSITIVE_INFINITY : (a / (NEVER - 1)) * durationS;
      }
    }

    const tris: number[][] = [];
    for (let r = 0; r < rows - 1; r += 1) {
      for (let c = 0; c < cols - 1; c += 1) {
        const a = r * cols + c;
        const b = a + 1;
        const d = a + cols;
        const e = d + 1;
        // Alternate the diagonal so the facets do not all lean one way.
        const pair = (r + c) % 2 === 0 ? [[a, b, e], [a, e, d]] : [[a, b, d], [b, e, d]];
        for (const tri of pair) {
          if (tri.some((k) => this.cover[k] > 0.5 && Number.isFinite(this.arrival[k]))) {
            tris.push(tri);
          }
        }
      }
    }
    const first = (tri: number[]) => Math.min(...tri.map((k) => this.arrival[k]));
    tris.sort((p, q) => first(p) - first(q));
    this.triangles = Int32Array.from(tris.flat());
    this.earliest = Float32Array.from(tris.map(first));
  }

  /** How far inside the flow a vertex is at time t: positive inside, 0 on the outline or front. */
  private inside(k: number, t: number): number {
    const edge = (this.cover[k] - 0.5) * 4;
    const arrive = this.arrival[k];
    const front = Number.isFinite(arrive) ? (t - arrive) / this.soft : -10;
    return Math.min(edge, front);
  }

  /** The flow as it stands `t` simulated seconds after release. */
  at(t: number): MeshFeatureCollection {
    const features: MeshFeatureCollection["features"] = [];
    const count = this.earliest.length;
    for (let n = 0; n < count && this.earliest[n] < t; n += 1) {
      const ks = [this.triangles[n * 3], this.triangles[n * 3 + 1], this.triangles[n * 3 + 2]];
      const vals = ks.map((k) => this.inside(k, t));
      const ring = clip(ks.map((k) => this.lonlat[k]), vals);
      if (!ring) {
        continue;
      }
      let depth = 0;
      let arrive = 0;
      let reached = 0;
      for (const k of ks) {
        depth += this.depth[k] / 3;
        if (Number.isFinite(this.arrival[k]) && this.arrival[k] <= t) {
          arrive += this.arrival[k];
          reached += 1;
        }
      }
      const tone = Math.round((1 - Math.min(1, Math.max(0, depth))) * (TONES.length - 1));
      const fresh = reached > 0 && t - arrive / reached < this.soft * 2.5;
      features.push({
        type: "Feature",
        properties: { color: fresh ? SNOUT_CSS[tone] : TONE_CSS[tone] },
        geometry: { type: "Polygon", coordinates: [ring] },
      });
    }
    return { type: "FeatureCollection", features };
  }
}

/** The part of a triangle where the value is positive, as a closed ring. Null when none is. */
function clip(points: Position[], vals: number[]): Position[] | null {
  if (vals.every((v) => v <= 0)) {
    return null;
  }
  const out: Position[] = [];
  for (let i = 0; i < 3; i += 1) {
    const j = (i + 1) % 3;
    const [p, q] = [points[i], points[j]];
    const [a, b] = [vals[i], vals[j]];
    if (a > 0) {
      out.push(p);
    }
    if (a > 0 !== b > 0) {
      const f = a / (a - b);
      out.push([p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f]);
    }
  }
  out.push(out[0]);
  return out;
}
