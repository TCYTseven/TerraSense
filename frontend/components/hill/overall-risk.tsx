import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import { formatScore, formatUtc } from "@/lib/format";
import type { HillView } from "@/lib/hill";

/** The worst point on any mapped trail and its level. Static mountains show their fixed level only. */
export default function OverallRisk({ hill }: { hill: HillView }) {
  const { level, score } = hill.risk;
  return (
    <section aria-labelledby="risk-heading" className={`border-t border-border px-5 py-4 ${LEVEL_TREATMENT[level]}`}>
      <h2 id="risk-heading" className="text-sm text-muted-foreground">
        Overall risk
      </h2>
      <p className="mt-2 flex items-baseline gap-3">
        {hill.isLive && score !== null && (
          <span className="font-mono text-4xl/10 font-semibold tracking-tight">{formatScore(score)}</span>
        )}
        <LevelWord level={level} className="text-base font-semibold" />
      </p>
      {!hill.isLive && (
        <p className="mt-2 text-base">No trails are mapped here. Analyze uses this summit&apos;s location, the risk model, and live weather.</p>
      )}
      {hill.isLive && hill.scoring && (
        <p className="mt-2 text-sm text-muted-foreground">
          Worst point on any of {hill.scoring.trailsScored} mapped trails ·{" "}
          <span className="font-mono">{Math.round(hill.scoring.shareAreaHigh * 100)}%</span> of the area at high or above ·
          scored <span className="font-mono">{formatUtc(hill.scoring.scoredAt)}</span>
        </p>
      )}
      {hill.isLive && !hill.scoring && (
        <p className="mt-2 text-sm text-muted-foreground">No saved heat map yet. Run Analyze now to score the trails.</p>
      )}
    </section>
  );
}
