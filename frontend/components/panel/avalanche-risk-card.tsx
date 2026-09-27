"use client";

import { useEffect, useState } from "react";
import { LEVEL_TEXT, LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import { getAvalancheRisk } from "@/lib/api";
import { formatLatLon, formatUtc, humanize, probabilityRiskLevel } from "@/lib/format";
import type { AvalancheRiskPrediction, LandslideRiskState, RiskLevel } from "@/lib/types";

const STATE_LABEL: Record<LandslideRiskState, string> = {
  HIGH_RISK: "High risk",
  NOT_HIGH_RISK: "Not high risk",
  UNCERTAIN: "Uncertain",
};

const STATE_TEXT: Record<LandslideRiskState, string> = {
  HIGH_RISK: "text-red-400",
  NOT_HIGH_RISK: "text-emerald-400",
  UNCERTAIN: "text-amber-400",
};

const REASON_LABEL: Record<string, string> = {
  FORECAST_UNAVAILABLE: "Snow forecast not connected",
  FORECAST_STALE: "Snow forecast stale",
  WEATHER_FEED_UNAVAILABLE: "Weather feed down",
  ESTIMATE_UNAVAILABLE: "No model value at this spot",
  OUT_OF_DISTRIBUTION: "Outside the study area",
};

function reasonLabel(code: string): string {
  return REASON_LABEL[code] ?? humanize(code);
}

function formatPercent(value: number): string {
  const percent = value * 100;
  if (percent < 0.1) return "<0.1%";
  if (percent < 9.95) return `${percent.toFixed(1)}%`;
  return `${Math.round(percent)}%`;
}

function windowLabel(start: string, end: string): string {
  return `${formatUtc(start).replace(" UTC", "")}–${formatUtc(end)}`;
}

interface Settled {
  key: string;
  prediction: AvalancheRiskPrediction | null;
  error: string | null;
}

export type AvalancheRiskPanelLayout = "full" | "summary" | "detailsOnly";

/**
 * Seven-day avalanche projection for catalog mountains. Hills use the landslide card instead.
 */
export default function AvalancheRiskCard({
  latitude,
  longitude,
  panelLayout = "full",
}: {
  latitude: number;
  longitude: number;
  panelLayout?: AvalancheRiskPanelLayout;
}) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);
  const key = `${latitude},${longitude},${attempt}`;
  const loading = settled?.key !== key;

  useEffect(() => {
    const controller = new AbortController();
    const requestKey = `${latitude},${longitude},${attempt}`;
    getAvalancheRisk(latitude, longitude, undefined, { signal: controller.signal }).then(
      (prediction) => {
        if (!controller.signal.aborted) setSettled({ key: requestKey, prediction, error: null });
      },
      (reason: unknown) => {
        if (controller.signal.aborted) return;
        const error = reason instanceof Error ? reason.message : "Risk check unavailable";
        setSettled({ key: requestKey, prediction: null, error });
      },
    );
    return () => controller.abort();
  }, [latitude, longitude, attempt]);

  const prediction = settled?.prediction ?? null;
  const level: RiskLevel | null =
    prediction?.probability != null ? probabilityRiskLevel(prediction.probability) : null;
  const summary = panelLayout === "summary";
  const detailsOnly = panelLayout === "detailsOnly";
  const showSummary = !detailsOnly;
  const showDetails = !summary;

  if (detailsOnly && (!settled || settled.error !== null || loading || !prediction || prediction.state === "UNCERTAIN")) {
    return null;
  }

  return (
    <section
      aria-labelledby={showSummary ? "cell-avalanche-heading" : undefined}
      className={`border-t border-border px-5 ${summary ? "py-3" : "py-4"} ${level && !summary ? LEVEL_TREATMENT[level] : ""}`}
    >
      {showSummary && (
        <>
          <div className="flex items-baseline justify-between gap-3">
            <h2 id="cell-avalanche-heading" className="text-sm text-muted-foreground">
              Avalanche risk · next 7 days
            </h2>
            {loading && settled && <span className="text-xs text-muted-foreground">Checking…</span>}
          </div>

          <div aria-live="polite" aria-busy={loading} className={loading && settled ? "opacity-50" : ""}>
            {!settled ? (
              <HeadlineSkeleton compact={summary} />
            ) : settled.error !== null ? (
              <p role="alert" className="mt-2 text-sm text-muted-foreground">
                Could not check this spot: {settled.error}{" "}
                <button
                  type="button"
                  onClick={() => setAttempt((n) => n + 1)}
                  disabled={loading}
                  className="font-medium text-primary underline decoration-1 underline-offset-3 disabled:opacity-40"
                >
                  Retry
                </button>
              </p>
            ) : (
              prediction && <Headline prediction={prediction} level={level} compact={summary} />
            )}
          </div>

          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            <span className="font-mono text-foreground">{formatLatLon(latitude, longitude)}</span>
            {" · "}
            Click the map to move this spot check.
          </p>
        </>
      )}

      {showDetails && prediction && settled?.error === null && (
        <div className={`space-y-3 text-sm ${detailsOnly ? "" : "mt-3"} ${loading ? "opacity-50" : ""}`}>
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Snow avalanche classifier</span> · terrain × snowpack
            loading for high peaks. Not an official danger rating.
          </p>
          {prediction.drivers.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {prediction.drivers.slice(0, 4).map((driver) => (
                <li key={driver.feature} className="text-foreground">
                  {driver.label || humanize(driver.feature)}
                  {driver.value !== null && <span className="font-mono"> ({driver.value.toFixed(2)})</span>}
                </li>
              ))}
            </ul>
          )}
          {prediction.state !== "UNCERTAIN" && <ClassifierAudit prediction={prediction} />}
        </div>
      )}
    </section>
  );
}

function HeadlineSkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <div className="mt-2 space-y-2" aria-label="Checking this spot">
      <div
        className={`animate-work rounded-sm bg-muted motion-reduce:animate-none ${compact ? "h-8 w-28" : "h-10 w-36"}`}
      />
      {!compact && <div className="h-4 w-56 animate-work rounded-sm bg-muted motion-reduce:animate-none" />}
    </div>
  );
}

function Headline({
  prediction,
  level,
  compact = false,
}: {
  prediction: AvalancheRiskPrediction;
  level: RiskLevel | null;
  compact?: boolean;
}) {
  const { probability, reason_codes: reasons, state } = prediction;
  if (probability === null) {
    if (reasons.includes("OUT_OF_DISTRIBUTION")) {
      return <p className="mt-2 text-base">Outside this peak&apos;s mapped study box.</p>;
    }
    if (state === "UNCERTAIN") {
      return (
        <p className="mt-2 text-base text-muted-foreground">
          Avalanche model abstains until snow forecast and artifacts are connected.
        </p>
      );
    }
    return (
      <div className="mt-2">
        <p className="text-base">No estimate for this spot.</p>
        {reasons.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">{reasons.map(reasonLabel).join(" · ")}</p>
        )}
      </div>
    );
  }
  return (
    <p className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span
        className={`font-mono font-semibold tracking-tight ${compact ? "text-3xl/9" : "text-4xl/10"} ${level ? LEVEL_TEXT[level] : ""}`}
      >
        {formatPercent(probability)}
      </span>
      {level && <LevelWord level={level} className={compact ? "text-sm font-semibold" : "text-base font-semibold"} />}
    </p>
  );
}

function ClassifierAudit({ prediction }: { prediction: AvalancheRiskPrediction }) {
  const { state } = prediction;
  const percent = (value: number | null, digits: number) => (value === null ? "—" : `${(value * 100).toFixed(digits)}%`);
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-baseline gap-1.5 text-muted-foreground [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-primary group-open:rotate-90">
          ▸
        </span>
        <span className="underline decoration-primary/60 decoration-1 underline-offset-3">Classifier:</span>
        <span className={`font-semibold ${STATE_TEXT[state]}`}>{STATE_LABEL[state]}</span>
      </summary>
      <div className="mt-2 space-y-2 text-muted-foreground">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <span>Window</span>
          <span className="text-right font-mono">
            {windowLabel(prediction.prediction_window.start, prediction.prediction_window.end)}
          </span>
          <span>Calibrated probability</span>
          <span className="text-right font-mono">{percent(prediction.calibrated_probability, 1)}</span>
          <span>Data quality</span>
          <span className="text-right font-mono">{percent(prediction.data_quality_score, 0)}</span>
        </div>
        {prediction.reason_codes.length > 0 && (
          <p>Reasons: {prediction.reason_codes.map(reasonLabel).join(" · ")}</p>
        )}
      </div>
    </details>
  );
}
