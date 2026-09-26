import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import { formatScore } from "@/lib/format";
import type { HillView } from "@/lib/hill";

/** The overall score and its level. Static mountains show their fixed level only. */
export default function OverallRisk({ hill }: { hill: HillView }) {
  const { level, score } = hill.risk;
  return (
    <section aria-labelledby="risk-heading" className={`border-t border-border px-5 py-4 ${LEVEL_TREATMENT[level]}`}>
      <h2 id="risk-heading" className="text-sm text-muted-foreground">
        Overall risk
      </h2>
      <p className="mt-2 flex items-baseline gap-3">
        {hill.isLive && <span className="font-mono text-4xl/10 font-semibold tracking-tight">{formatScore(score)}</span>}
        <LevelWord level={level} className="text-base font-semibold" />
      </p>
      {!hill.isLive && <p className="mt-2 text-base">Display marker. Live analysis runs on Mount Rainier only.</p>}
      {hill.isDemo && (
        <p className="mt-2 text-sm text-muted-foreground">Illustrative scores until the trail model lands.</p>
      )}
    </section>
  );
}
