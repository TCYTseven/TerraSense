import type { Simulation, SimulationCallout } from "@/lib/types";

/** Simulated clock, `T+04:30`. Mono, because it is a number with its unit. */
export function simulationClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `T+${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

function miles(meters: number): string {
  return (meters / 1609.344).toFixed(1);
}

/**
 * The time span of a runout, pinned to the top of the mountain view, plus the
 * callouts that have been reached. The bar is a display: it does not scrub.
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
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 border-b border-border bg-card px-4 py-2 pr-14">
          <p className="text-sm text-muted-foreground">Tracing the flow…</p>
        </div>
      );
    }
    return null;
  }

  const duration = simulation.duration_s || simulation.frames.at(-1)?.t_s || 1;
  const progress = Math.min(1, timeS / duration);
  const step = [...simulation.steps].reverse().find((item) => item.t_s <= timeS + 0.05);
  const visible = simulation.callouts.filter((callout) => callout.t_s <= timeS + 0.05);
  const trailCount = new Set(simulation.steps.filter((item) => item.kind === "trail").map((item) => item.trail_name)).size;
  const finished = phase === "finished";

  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 border-b border-border bg-card px-4 py-2 pr-14">
        <div className="flex items-baseline justify-between gap-3">
          <p className="min-w-0 truncate text-sm text-foreground">{step?.title ?? "Slope releases"}</p>
          <p className="shrink-0 font-mono text-sm text-foreground">{simulationClock(timeS)}</p>
        </div>
        <div className="mt-2 h-1.5 bg-muted" aria-hidden>
          <div className="h-full bg-foreground" style={{ width: `${progress * 100}%` }} />
        </div>
        <div className="mt-1 flex justify-between font-mono text-xs text-muted-foreground">
          <span>{simulationClock(0)}</span>
          <span>{simulationClock(duration / 2)}</span>
          <span>{simulationClock(duration)}</span>
        </div>
        <p className="mt-1.5 text-sm text-muted-foreground">{simulation.method}</p>
        {finished && (
          <p className="mt-1 text-sm text-foreground">
            Simulation finished. The flow ran {miles(simulation.distance_m)} mi and crossed {trailCount}{" "}
            {trailCount === 1 ? "trail" : "trails"}.
            {simulation.callouts_from_templates ? " Callouts came from templates. The AI didn't answer." : ""}
          </p>
        )}
      </div>
      {visible.length > 0 && (
        <div className="pointer-events-none absolute inset-x-4 bottom-16 z-20 flex max-h-[40%] flex-col gap-2 overflow-hidden">
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
    <div className="border-l-2 border-foreground/40 bg-card px-3 py-2">
      <p className="flex items-baseline justify-between gap-3 text-sm text-muted-foreground">
        <span>{audience}</span>
        <span className="font-mono">{simulationClock(callout.t_s)}</span>
      </p>
      <p className="mt-1 text-base text-foreground">{callout.text}</p>
    </div>
  );
}
