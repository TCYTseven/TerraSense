import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import { formatScore } from "@/lib/format";
import type { HillView } from "@/lib/hill";

const SOURCE_NOTE: Record<NonNullable<HillView["scoreSource"]>, string> = {
  run: "Mean of the five trails' worst points on the last run's map.",
  preview: "Preview on the current rain data. Analyze now to run the agents on it.",
  illustrative: "Illustrative scores: the trail-risk API did not answer.",
};

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
      {hill.scoreSource && <p className="mt-2 text-sm text-muted-foreground">{SOURCE_NOTE[hill.scoreSource]}</p>}
    </section>
  );
}
