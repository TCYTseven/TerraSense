import type { RiskLevel } from "./types";

/**
 * The neutral and accent palette (basalt and glacier) for code that cannot read
 * CSS variables, such as the WebGL globe, Mapbox paint, and the generated app icon.
 * Values come from the Design Language section of context/TerraSense.md. Keys follow
 * the role names in context/design-addendum.md's Tokens table. Mirrors the tokens in
 * app/globals.css. Change both together.
 */
export const THEME = {
  background: "#0D0C0A",
  muted: "#13120F",
  card: "#1A1814",
  foreground: "#ECE6DC",
  mutedForeground: "#9C9387",
  primary: "#7FDDE6",
} as const;

/** Risk colors. They mark risk and nothing else. */
export const RISK_COLORS = {
  low: "#22C55E",
  moderate: "#F59E0B",
  high: "#F97316",
  extreme: "#EF4444",
} as const satisfies Record<RiskLevel, string>;
