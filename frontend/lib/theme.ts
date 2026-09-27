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

/** Home / globe screen only. Mountain pages keep the dark dispatch theme in :root. */
export const HOME_THEME = {
  background: "#F5F2EB",
  muted: "#EBE6DD",
  card: "#FFFFFF",
  foreground: "#1A1814",
  mutedForeground: "#6B6359",
  primary: "#2BA8B5",
  atmosphere: "#7FDDE6",
} as const;

/**
 * The simulated debris flow, drawn as dirt on the ground. Index is the band's
 * `shade` from the API: 0 is the dark core, the last is the pale outer edge.
 * Not a risk color: the flow's level is in the steps and callouts.
 */
export const FLOW_COLORS = ["#4A2C16", "#6B4226", "#8B5E3C", "#AD8358", "#CDAE84"] as const;

/**
 * The same runout on a mountain, drawn as an avalanche: light blue at the deep core,
 * paling toward white as the snow thins and spreads. Indexed like FLOW_COLORS.
 */
export const AVALANCHE_COLORS = ["#7FB8E0", "#99C8E8", "#B4D8F0", "#CFE7F6", "#EAF5FC"] as const;

/** Which ramp a runout is drawn in: dirt for landslides, snow for mountain avalanches. */
export type FlowPalette = "debris" | "snow";

export function flowColors(palette: FlowPalette): readonly string[] {
  return palette === "snow" ? AVALANCHE_COLORS : FLOW_COLORS;
}

/** Risk colors. They mark risk and nothing else. */
export const RISK_COLORS = {
  low: "#22C55E",
  moderate: "#F59E0B",
  high: "#F97316",
  extreme: "#EF4444",
} as const satisfies Record<RiskLevel, string>;
