import { FLOW_COLORS } from "./theme";
import type { RunoutField } from "./types";

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
/** Largest canvas side. The field is upsampled up to UPSAMPLE times, then capped here. */
const MAX_CANVAS_PX = 1024;
const UPSAMPLE = 8;
const OPACITY = 0.85;
/** The pale rim the polygon edge line used to draw. */
const RIM: RGB = [236, 230, 220];
/** Fresh debris at the snout is darker and wetter than what has settled behind it. */
const SNOUT: RGB = [52, 30, 14];

type RGB = [number, number, number];

function hexRgb(hex: string): RGB {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

// FLOW_COLORS runs dark core first, so depth 1 is index 0.
const RAMP = FLOW_COLORS.map(hexRgb);

function rampColor(depth: number): RGB {
  const pos = (1 - Math.min(1, Math.max(0, depth))) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = RAMP[i];
  const b = RAMP[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

function decode(base64: string): Uint8Array {
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    out[i] = raw.charCodeAt(i);
  }
  return out;
}

/**
 * Paints a runout field into a canvas at any simulated time. The field is decoded and
 * upsampled once (bilinear, so cell edges never show); each draw only sweeps the front.
 */
export class RunoutPainter {
  readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly image: ImageData;
  private readonly arrival: Float32Array;
  private readonly cover: Float32Array;
  private readonly depth: Float32Array;
  private readonly base: Uint8ClampedArray;
  private readonly soft: number;

  constructor(field: RunoutField, durationS: number) {
    const { width, height } = field;
    const scale = Math.max(1, Math.min(UPSAMPLE, Math.floor(MAX_CANVAS_PX / Math.max(width, height))));
    const w = width * scale;
    const h = height * scale;
    this.canvas = document.createElement("canvas");
    this.canvas.width = w;
    this.canvas.height = h;
    const ctx = this.canvas.getContext("2d", { willReadFrequently: false });
    if (!ctx) {
      throw new Error("No 2D canvas");
    }
    this.ctx = ctx;
    this.image = ctx.createImageData(w, h);
    // The front's soft edge in simulated seconds: wide enough to read as a moving surge.
    this.soft = Math.max(2, durationS * 0.035);

    const coverSrc = decode(field.cover);
    const depthSrc = decode(field.depth);
    const arrivalBytes = decode(field.arrival);
    const arrivalSrc = new Uint16Array(arrivalBytes.buffer, arrivalBytes.byteOffset, width * height);
    // Uint16Array reads native order; every browser we target is little-endian, as the wire is.

    this.arrival = new Float32Array(w * h);
    this.cover = new Float32Array(w * h);
    this.depth = new Float32Array(w * h);
    this.base = new Uint8ClampedArray(w * h * 3);

    for (let y = 0; y < h; y += 1) {
      const v = Math.min(height - 1, Math.max(0, (y + 0.5) / scale - 0.5));
      const y0 = Math.floor(v);
      const y1 = Math.min(height - 1, y0 + 1);
      const fy = v - y0;
      for (let x = 0; x < w; x += 1) {
        const u = Math.min(width - 1, Math.max(0, (x + 0.5) / scale - 0.5));
        const x0 = Math.floor(u);
        const x1 = Math.min(width - 1, x0 + 1);
        const fx = u - x0;
        const idx = [y0 * width + x0, y0 * width + x1, y1 * width + x0, y1 * width + x1];
        const wts = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
        let cover = 0;
        let depth = 0;
        let arrive = 0;
        let arriveW = 0;
        for (let k = 0; k < 4; k += 1) {
          cover += (coverSrc[idx[k]] / 255) * wts[k];
          depth += (depthSrc[idx[k]] / 255) * wts[k];
          const a = arrivalSrc[idx[k]];
          if (a !== NEVER) {
            arrive += (a / (NEVER - 1)) * durationS * wts[k];
            arriveW += wts[k];
          }
        }
        const p = y * w + x;
        this.cover[p] = cover;
        this.depth[p] = depth;
        this.arrival[p] = arriveW > 0 ? arrive / arriveW : Number.POSITIVE_INFINITY;
        const [r, g, b] = rampColor(depth);
        this.base[p * 3] = r;
        this.base[p * 3 + 1] = g;
        this.base[p * 3 + 2] = b;
      }
    }
  }

  /** Draws the flow as it stands `t` simulated seconds after release. */
  draw(t: number): void {
    const out = this.image.data;
    const n = this.arrival.length;
    const soft = this.soft;
    for (let p = 0; p < n; p += 1) {
      const age = t - this.arrival[p];
      const cover = this.cover[p];
      const o = p * 4;
      if (!(age > 0) || cover < 0.35) {
        out[o + 3] = 0;
        continue;
      }
      // Anti-aliased outline at cover 0.5, and a front that eases in rather than popping.
      const edge = smoothstep(0.4, 0.6, cover);
      const front = smoothstep(0, soft, age);
      const snout = (1 - smoothstep(0, soft * 2.5, age)) * 0.45;
      const rim = (1 - smoothstep(0.5, 0.68, cover)) * 0.4;
      let r = this.base[p * 3];
      let g = this.base[p * 3 + 1];
      let b = this.base[p * 3 + 2];
      r += (SNOUT[0] - r) * snout;
      g += (SNOUT[1] - g) * snout;
      b += (SNOUT[2] - b) * snout;
      r += (RIM[0] - r) * rim;
      g += (RIM[1] - g) * rim;
      b += (RIM[2] - b) * rim;
      out[o] = r;
      out[o + 1] = g;
      out[o + 2] = b;
      out[o + 3] = 255 * OPACITY * edge * front;
    }
    this.ctx.putImageData(this.image, 0, 0);
  }
}
