import type { RiskLevel } from "./types";

/**
 * The dark dispatch palette for code that cannot use CSS classes, such as the
 * WebGL globe. Mirrors the tokens in app/globals.css. Change both together.
 */
export const THEME = {
  background: "#0A0E14",
  surface: "#0F1419",
  panel: "#151B23",
  foreground: "#E6EDF3",
  muted: "#8B949E",
  accent: "#22D3EE",
} as const;

/** Risk colors. They mark risk and nothing else. */
export const RISK_COLORS = {
  low: "#22C55E",
  moderate: "#F59E0B",
  high: "#F97316",
  extreme: "#EF4444",
} as const satisfies Record<RiskLevel, string>;
