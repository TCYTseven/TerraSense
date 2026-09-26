import type { Simulation, SimulationCallout } from "@/lib/types";

/** Simulated clock, `T+04:30`. Mono, because it is a number with its unit. */
export function simulationClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `T+${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

/**
 * The runout timeline pinned to the top of the mountain view, plus callouts
 * reached so far. The bar is display-only; it does not scrub.
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
  const visible = simulation.callouts.filter((callout) => callout.t_s <= timeS + 0.05);
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
      {visible.length > 0 && (
        <div className="pointer-events-none absolute inset-x-3 bottom-14 z-20 flex max-h-[36%] flex-col gap-1.5 overflow-hidden md:inset-x-4 md:bottom-16">
          {visible.map((callout) => (
            <Callout key={callout.id} callout={callout} />
          ))}
        </div>
      )}
    </>
  );
}

function Callout({ callout }: { callout: SimulationCallout }) {
  const audience = callout.audience === "public" ? "Public notice, draft, not sent" : "Rangers";
  return (
    <div className="border-l-2 border-foreground/35 bg-card/95 px-2.5 py-1.5 backdrop-blur-sm">
      <p className="flex items-baseline justify-between gap-2 text-[11px] leading-tight text-muted-foreground">
        <span className="min-w-0 truncate">{audience}</span>
        <span className="shrink-0 font-mono tabular-nums">{simulationClock(callout.t_s)}</span>
      </p>
      <p className="mt-0.5 text-sm leading-snug text-foreground">{callout.text}</p>
    </div>
  );
}
