import type { RiskLevel } from "./types";

/**
 * The neutral and accent palette (stone and glacier, light) for code that cannot read CSS
 * variables: the WebGL globe, the map's paint, and the generated app icon. Values come from
 * the Design Language section of context/TerraSense.md. Keys follow the role names in
 * context/design-addendum.md's Tokens table. Mirrors the tokens in app/globals.css.
 * Change both together.
 */
export const THEME = {
  background: "#F6F8FA",
  muted: "#EEF2F6",
  card: "#FFFFFF",
  foreground: "#0F172A",
  mutedForeground: "#5B6576",
  primary: "#0E7490",
} as const;

/** Risk colors. They mark risk and nothing else. */
export const RISK_COLORS = {
  low: "#22C55E",
  moderate: "#F59E0B",
  high: "#F97316",
  extreme: "#EF4444",
} as const satisfies Record<RiskLevel, string>;

/**
 * Globe-only colors: its lights, its atmosphere, and the parts of a marker that are
 * not risk. The Earth itself is the texture in public/globe/earth-light.jpg.
 */
export const GLOBE_COLORS = {
  /** Hemisphere light from above and from below. Nearly even, so no side of the globe goes dark. */
  sky: "#FFFFFF",
  ground: "#EBF0F5",
  /** Soft key light that follows the camera, faintly warm. */
  sun: "#FFF8EE",
  /** The rim of air around the globe, drawn over the light page with normal blending. */
  atmosphere: "#A9D2F2",
  /** Marker snow caps. */
  snow: "#FFFFFF",
  /** The soft contact shadow under a marker. */
  shadow: THEME.foreground,
} as const;
