import { riskLabel } from "@/lib/format";
import type { RiskLevel } from "@/lib/types";

// Literal class names so Tailwind generates each one.
const DOT_CLASS: Record<RiskLevel, string> = {
  low: "bg-risk-low",
  moderate: "bg-risk-moderate",
  high: "bg-risk-high",
  extreme: "bg-risk-extreme",
};

/** A risk-colored dot and the level name, such as "High risk". */
export default function RiskBadge({
  level,
  className = "",
}: {
  level: RiskLevel;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span aria-hidden className={`size-2 shrink-0 rounded-full ${DOT_CLASS[level]}`} />
      <span>{riskLabel(level)} risk</span>
    </span>
  );
}
