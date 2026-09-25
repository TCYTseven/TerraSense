import Link from "next/link";
import { formatFeet, formatInches, formatMileRange, formatScore, timeAgo } from "@/lib/format";
import { RISK_LEVELS, type AgentName, type Hazard, type MountainDetail, type RiskLevel, type Run } from "@/lib/types";
import AgentRows, { type RowState } from "./agent-rows";
import HazardBlock from "./hazard-block";
import { LEVEL_TREATMENT, LevelWord, NeedsReviewTag } from "./level";

export interface RangerPanelProps {
  mountain: MountainDetail;
  /** The pin's hazard, open in the panel while the pin is selected. */
  hazard: Hazard | null;
  hazardOpen: boolean;
  onCloseHazard: () => void;
  /** The run the agent rows show: the one going now, or the latest. */
  run: Run | null;
  rows: RowState[];
  analyzing: boolean;
  /** The status line under the agent rows, for a finished or failed run. */
  status: string | null;
  heatMapIsStandIn: boolean;
  onAnalyze: () => void;
  onOpenReasoning: (agent: AgentName) => void;
}

function highest(levels: (RiskLevel | null)[]): RiskLevel | null {
  const scored = levels.filter((level): level is RiskLevel => level !== null);
  return scored.length ? scored.reduce((a, b) => (RISK_LEVELS.indexOf(b) > RISK_LEVELS.indexOf(a) ? b : a)) : null;
}

function Label({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-muted-foreground">{children}</h2>;
}

/**
 * The ranger's dispatch board, top to bottom (design addendum, Panel): header, overall risk,
 * the hazard (with the pin), rain, trails, agents, the status line, and the action.
 */
export default function RangerPanel(props: RangerPanelProps) {
  const { mountain, hazard, run } = props;
  const live = mountain.is_live;
  // No level, no color: a live mountain shows a level only once it has a hazard or an analysis.
  const level: RiskLevel | null = live
    ? hazard?.severity ?? (mountain.last_analyzed_at ? mountain.current_risk_level : null)
    : mountain.current_risk_level;
  const synthesis = run?.status === "done" && hazard?.run_id === run.id ? run.agents.synthesizer?.payload : undefined;
  const summary = typeof synthesis?.summary === "string" ? synthesis.summary : null;
  const sentence = !live
    ? "Display marker. Live analysis runs on Mount Rainier only."
    : summary ?? hazard?.what ?? (level ? null : "Not analyzed yet. Analyze now scores the next 72 hours.");
  const refreshed = mountain.last_analyzed_at
    ? `Updated ${timeAgo(mountain.last_analyzed_at)}`
    : hazard ? "Preview from the heat map. Not analyzed by the agents yet." : null;

  const heroTrails = mountain.trails.filter((trail) => trail.segments.length > 0);
  const otherTrails = mountain.trails.filter((trail) => trail.segments.length === 0);

  return (
    <aside className="flex min-h-0 flex-col border-t border-border bg-card md:w-[clamp(360px,30vw,440px)] md:shrink-0 md:border-l md:border-t-0">
      <div className="min-h-0 flex-1 md:overflow-y-auto">
        <header className="px-5 pb-4 pt-5">
          <Link href="/" className="text-xs text-primary underline decoration-1 underline-offset-3">
            Back to the globe
          </Link>
          <h1 className="mt-3 text-2xl/7 font-semibold tracking-[-0.01em]">{mountain.name}</h1>
          <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-muted-foreground">
            <span className="font-mono text-[0.92em]">{formatFeet(mountain.elevation_m)}</span>
            <span>{mountain.region}</span>
          </p>
        </header>

        <section
          aria-labelledby="risk-heading"
          className={`border-t border-border px-5 py-4 ${level ? LEVEL_TREATMENT[level] : ""}`}
        >
          <Label>
            <span id="risk-heading">Overall risk</span>
          </Label>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-base">
            {level ? (
              <LevelWord level={level} className="font-semibold" />
            ) : (
              <span className="text-muted-foreground">Not analyzed yet</span>
            )}
            {live && hazard?.needs_review && <NeedsReviewTag />}
          </p>
          {sentence && <p className="mt-2 text-base">{sentence}</p>}
          {refreshed && (
            <p className="mt-2 text-xs text-muted-foreground" suppressHydrationWarning>
              {refreshed}
            </p>
          )}
          {live && props.heatMapIsStandIn && (
            <p className="mt-1 text-xs text-muted-foreground">
              The heat map shows terrain susceptibility until the rain model lands.
            </p>
          )}
        </section>

        {live && hazard && props.hazardOpen && <HazardBlock hazard={hazard} onClose={props.onCloseHazard} />}

        {live && (
          <section aria-label="Rain" className="border-t border-border px-5 py-4">
            <Label>Rain</Label>
            {run?.rain ? (
              <>
                <dl className="mt-2 space-y-1 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt>Past 72 hours</dt>
                    <dd className="font-mono text-[0.92em]">{formatInches(run.rain.past_72h_mm)}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt>Next 24 hours</dt>
                    <dd className="font-mono text-[0.92em]">{formatInches(run.rain.next_24h_mm)}</dd>
                  </div>
                </dl>
                {run.rain.source === "fixture" && (
                  <p className="mt-2 text-xs text-muted-foreground">A saved test storm, not observed rain.</p>
                )}
              </>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">Rain totals arrive with the first analysis.</p>
            )}
          </section>
        )}

        {mountain.trails.length > 0 && (
          <section aria-label="Trails" className="border-t border-border px-5 py-4">
            <Label>Trails</Label>
            <ul className="mt-2 space-y-2">
              {heroTrails.map((trail) => {
                const trailLevel = highest(trail.segments.map((s) => s.risk_level));
                const score = Math.max(...trail.segments.map((s) => s.probability ?? 0));
                const flagged = hazard && hazard.trail_id === trail.id && hazard.start_mile !== null && hazard.end_mile !== null;
                return (
                  <li key={trail.id}>
                    <div className="flex items-baseline justify-between gap-4 text-sm">
                      <span>{trail.name}</span>
                      {trailLevel ? (
                        <span className="flex shrink-0 items-baseline gap-2">
                          <LevelWord level={trailLevel} />
                          <span className="font-mono text-[0.92em] text-muted-foreground">{formatScore(score)}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">Not scored</span>
                      )}
                    </div>
                    {flagged && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Flagged <span className="font-mono text-[0.92em]">{formatMileRange(hazard.start_mile!, hazard.end_mile!)}</span>
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
            {otherTrails.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-primary underline decoration-1 underline-offset-3">
                  {otherTrails.length} more trails on the map
                </summary>
                <ul className="mt-2 columns-2 gap-4 text-xs text-muted-foreground">
                  {otherTrails.map((trail) => (
                    <li key={trail.id} className="break-inside-avoid py-0.5">
                      {trail.name}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        )}

        {live && (
          <section id="agents" aria-label="Agents" className="border-t border-border px-5 py-4">
            <div className="flex items-baseline justify-between gap-4">
              <Label>Agents</Label>
              <button
                type="button"
                onClick={() => props.onOpenReasoning("terrain")}
                className="text-xs text-primary underline decoration-1 underline-offset-3"
              >
                Reasoning
              </button>
            </div>
            <AgentRows rows={props.rows} onOpen={props.onOpenReasoning} />
            {props.status && (
              <p role="status" className="mt-3 border-l-2 border-foreground/40 pl-2 text-xs">
                {props.status}
              </p>
            )}
          </section>
        )}
      </div>

      {live && (
        <footer className="border-t border-border px-5 py-4">
          <button
            type="button"
            onClick={props.onAnalyze}
            disabled={props.analyzing}
            className="h-10 w-full rounded-md bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
          >
            {props.analyzing ? "Analyzing…" : "Analyze now"}
          </button>
        </footer>
      )}
    </aside>
  );
}
