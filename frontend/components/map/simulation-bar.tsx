import type { Simulation, SimulationCallout } from "@/lib/types";

/** Simulated clock, `T+04:30`. Mono, because it is a number with its unit. */
export function simulationClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `T+${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

/**
 * The runout timeline pinned to the top of the mountain view, plus one community
 * alert box when the simulation backend returns it.
 */
export default function SimulationBar({
  phase,
  simulation,
  timeS,
}: {
  phase: "idle" | "loading" | "playing" | "finished" | "error";
  simulation: Simulation | null;
  timeS: number;
}) {
  if (phase === "idle" || phase === "error" || !simulation) {
    if (phase === "loading") {
      return (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 border-b border-border/80 bg-card/95 px-3 py-1.5 pr-12 backdrop-blur-sm">
          <div className="h-1 animate-pulse bg-muted" aria-hidden />
          <p className="sr-only">Tracing the flow</p>
        </div>
      );
    }
    return null;
  }

  const duration = simulation.duration_s || simulation.frames.at(-1)?.t_s || 1;
  const progress = Math.min(1, timeS / duration);
  const step = [...simulation.steps].reverse().find((item) => item.t_s <= timeS + 0.05);
  const community = simulation.callouts.find(
    (callout) => callout.audience === "communities" && callout.t_s <= timeS + 0.05,
  );
  const waitingForCommunity =
    (phase === "playing" || phase === "finished") &&
    !community &&
    !simulation.callouts.some((c) => c.audience === "communities");
  const stepLabel = step?.title ?? "Slope releases";

  return (
    <>
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-20 border-b border-border/80 bg-card/95 px-3 py-1.5 pr-12 backdrop-blur-sm"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={timeS}
        aria-valuetext={`${simulationClock(timeS)} — ${stepLabel}`}
      >
        <div className="flex items-center gap-2.5">
          <div className="h-1 min-w-0 flex-1 bg-muted" aria-hidden>
            <div className="h-full bg-foreground transition-[width] duration-300 ease-linear" style={{ width: `${progress * 100}%` }} />
          </div>
          <p className="shrink-0 font-mono text-[11px] leading-none tabular-nums text-foreground">{simulationClock(timeS)}</p>
        </div>
      </div>
      {(community || waitingForCommunity) && (
        <div className="pointer-events-none absolute bottom-14 left-3 right-[4.75rem] z-20 md:bottom-16 md:left-4 md:right-[5.25rem]">
          {community ? (
            <CommunityAlert callout={community} />
          ) : (
            <div className="border-l-4 border-foreground/30 bg-card/95 px-3 py-2.5 backdrop-blur-md">
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                Communities to alert
              </p>
              <p className="mt-2 text-base font-semibold text-foreground animate-pulse">Finding villages in path…</p>
            </div>
          )}
        </div>
      )}
    </>
  );
}

/** Action line only — place names live in the bold headline, not repeated here. */
function alertAction(text: string, places: string[]): string {
  let body = text.trim();
  for (const place of places) {
    body = body.replaceAll(place, "").replaceAll(place.replace(/^(Village|Town|Monastery)\s+/i, ""), "");
  }
  body = body.replace(/\s{2,}/g, " ").trim();
  const firstSentence = body.split(/(?<=[.!?])\s+/)[0] ?? body;
  const cap = 120;
  if (firstSentence.length <= cap) {
    return firstSentence;
  }
  return `${firstSentence.slice(0, cap - 1).trim()}…`;
}

function CommunityAlert({ callout }: { callout: SimulationCallout }) {
  const places = callout.places?.filter(Boolean) ?? [];
  const action = alertAction(callout.text, places);

  return (
    <div className="border-l-4 border-amber-500 bg-card/95 px-3 py-3 shadow-lg backdrop-blur-md md:px-4 md:py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {places.length > 0 ? (
            <>
              <p className="text-lg font-bold leading-tight tracking-tight text-foreground md:text-xl">
                {places.join(" · ")}
              </p>
              {action.length > 0 && (
                <p className="mt-1.5 text-sm leading-snug text-muted-foreground line-clamp-2">{action}</p>
              )}
            </>
          ) : (
            <p className="text-lg font-bold leading-snug text-foreground">{callout.text}</p>
          )}
        </div>
        <span className="shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
          {simulationClock(callout.t_s)}
        </span>
      </div>
    </div>
  );
}
