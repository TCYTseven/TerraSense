import { formatSignedFeet, formatSignedMiles } from "@/lib/format";
import type { Forecast } from "@/lib/types";
import { LevelWord } from "./level";

export type HikerCardState = { kind: "loading" } | { kind: "error" } | { kind: "ready"; forecast: Forecast };

/**
 * The hiker card (design addendum, Hiker card): it replaces the ranger panel's content in place.
 * Trail, level word, the Alert Writer's one sentence, and the bypass with values from
 * GET /forecast. It never shows drivers, probability, or confidence.
 */
export default function HikerCard({ state, onBack }: { state: HikerCardState; onBack: () => void }) {
  return (
    <section aria-label="Hiker forecast" className="flex-1 p-7">
      <button
        type="button"
        onClick={onBack}
        className="text-base text-primary underline decoration-1 underline-offset-3"
      >
        Back to ranger view
      </button>

      {state.kind === "loading" && (
        <div aria-hidden className="mt-8 space-y-4">
          <div className="h-5 w-40 animate-work rounded-sm bg-muted motion-reduce:animate-none" />
          <div className="h-10 w-32 animate-work rounded-sm bg-muted motion-reduce:animate-none" />
          <div className="h-16 w-full animate-work rounded-sm bg-muted motion-reduce:animate-none" />
        </div>
      )}

      {state.kind === "error" && (
        <p role="status" className="mt-8 border-l-2 border-foreground/40 pl-2 text-xs">
          The hiker forecast didn&apos;t load. Go back and open it again.
        </p>
      )}

      {state.kind === "ready" && (
        <div className="mt-8">
          {state.forecast.trail_name && <p className="text-lg text-muted-foreground">{state.forecast.trail_name}</p>}
          <p className="mt-2 text-4xl font-semibold">
            <LevelWord level={state.forecast.level} />
          </p>
          <p className="mt-4 text-xl/8">{state.forecast.sentence}</p>
          {state.forecast.bypass && (
            <div className="mt-6">
              <p className="text-lg font-medium">{state.forecast.bypass.name}</p>
              <p className="mt-1 flex gap-4 font-mono text-base">
                <span>{formatSignedMiles(state.forecast.bypass.added_km)}</span>
                <span>{formatSignedFeet(state.forecast.bypass.added_elevation_m)}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
