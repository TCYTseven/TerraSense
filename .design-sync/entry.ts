// The surface synced to Claude Design: RiskBadge and its risk helpers. Tokens come
// from .design-sync/tokens.css (design addendum + spec), not from this entry.
// THEME from lib/theme.ts stays out: it names the cyan "accent", which the design
// addendum's Tokens rule 1 forbids. The globe components stay out too; they need
// WebGL, the Next router, and the API. See .design-sync/NOTES.md.
export { default as RiskBadge } from "@/components/risk-badge";
export { RISK_LEVELS } from "@/lib/types";
export type { RiskLevel } from "@/lib/types";
export { riskLabel } from "@/lib/format";
export { RISK_COLORS } from "@/lib/theme";
