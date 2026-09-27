/**
 * Color and light math for the runout mesh.
 *
 * Ramps are blended in OKLab (Ottosson 2020), a perceptual space, so equal steps along a ramp
 * look like equal steps and the midtones do not go muddy the way an sRGB blend does. Light is
 * applied in linear RGB, where multiplying by a brightness is physically meaningful, then
 * encoded back to sRGB. Each facet is lit with Lambert's cosine law from the same sun the
 * map's hillshade uses, so the flow's relief agrees with the terrain under it.
 */

/** Linear-light RGB, each channel 0 to 1. */
export type LinearRgb = [number, number, number];
/** A direction in local metres: east, north, up. */
export type Vec3 = [number, number, number];

// MapLibre's hillshade defaults: the sun sits 335 degrees clockwise from the top of the
// viewport ("viewport" anchor) and 45 degrees above the horizon.
export const SUN_DIRECTION_DEG = 335;
export const SUN_ALTITUDE_DEG = 45;

export function hexToLinear(hex: string): LinearRgb {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((c) => srgbToLinear(c / 255)) as LinearRgb;
}

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(v: number): number {
  const c = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
  return Math.round(Math.min(1, Math.max(0, c)) * 255);
}

/** A CSS color for a linear-light color. Channels past 1 clip to white, like sunlit snow. */
export function linearToCss([r, g, b]: LinearRgb): string {
  return `rgb(${linearToSrgb(r)}, ${linearToSrgb(g)}, ${linearToSrgb(b)})`;
}

export function linearToOklab([r, g, b]: LinearRgb): Vec3 {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

export function oklabToLinear([L, a, b]: Vec3): LinearRgb {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}

function mix(a: Vec3, b: Vec3, t: number): Vec3 {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/**
 * `steps` colors evenly along a ramp through `stops`, blended in OKLab. Index 0 is the first
 * stop and the last index is the last stop. Returned in linear light, ready to be lit.
 */
export function oklabRamp(stops: readonly LinearRgb[], steps: number): LinearRgb[] {
  const labs = stops.map(linearToOklab);
  const out: LinearRgb[] = [];
  for (let i = 0; i < steps; i += 1) {
    const at = (i / (steps - 1)) * (labs.length - 1);
    const low = Math.min(Math.floor(at), labs.length - 2);
    out.push(oklabToLinear(mix(labs[low], labs[low + 1], at - low)));
  }
  return out;
}

/** Each stop moved `amount` of the way toward `target`, in OKLab. */
export function towardInOklab(stops: readonly LinearRgb[], target: LinearRgb, amount: number): LinearRgb[] {
  const goal = linearToOklab(target);
  return stops.map((stop) => oklabToLinear(mix(linearToOklab(stop), goal, amount)));
}

/**
 * The sun as a unit vector in east, north, up. The hillshade's light is anchored to the
 * viewport, so its compass azimuth turns with the map: the screen's top faces `bearingDeg`.
 */
export function sunVector(bearingDeg: number, directionDeg = SUN_DIRECTION_DEG, altitudeDeg = SUN_ALTITUDE_DEG): Vec3 {
  const azimuth = ((bearingDeg + directionDeg) * Math.PI) / 180;
  const altitude = (altitudeDeg * Math.PI) / 180;
  return [Math.sin(azimuth) * Math.cos(altitude), Math.cos(azimuth) * Math.cos(altitude), Math.sin(altitude)];
}

/** The upward unit normal of the plane through three points, from the cross product of two edges. */
export function facetNormal(p0: Vec3, p1: Vec3, p2: Vec3): Vec3 {
  const u: Vec3 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
  const v: Vec3 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
  let n: Vec3 = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const length = Math.hypot(n[0], n[1], n[2]);
  if (length === 0) {
    return [0, 0, 1];
  }
  n = [n[0] / length, n[1] / length, n[2] / length];
  return n[2] < 0 ? [-n[0], -n[1], -n[2]] : n;
}

/**
 * Brightness for a facet under Lambert's cosine law, ambient + (1 - ambient) max(0, n . sun),
 * divided by the same for flat ground. Flat ground keeps its color exactly; slopes facing the
 * sun brighten and slopes facing away darken, never below ambient.
 */
export function lambertShade(normal: Vec3, sun: Vec3, ambient: number): number {
  const lit = (n: Vec3) => ambient + (1 - ambient) * Math.max(0, n[0] * sun[0] + n[1] * sun[1] + n[2] * sun[2]);
  return lit(normal) / lit([0, 0, 1]);
}

export function scaleLinear([r, g, b]: LinearRgb, k: number): LinearRgb {
  return [r * k, g * k, b * k];
}
