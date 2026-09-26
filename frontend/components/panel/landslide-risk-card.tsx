"use client";

import { useEffect, useState } from "react";
import { LEVEL_TEXT, LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import { getLandslideRisk } from "@/lib/api";
import { formatLatLon, formatUtc, humanize } from "@/lib/format";
import type { LandslideRiskPrediction, LandslideRiskState, RiskEstimate, RiskEstimateDriver } from "@/lib/types";

const STATE_LABEL: Record<LandslideRiskState, string> = {
  HIGH_RISK: "High risk",
  NOT_HIGH_RISK: "Not high risk",
  UNCERTAIN: "Uncertain",
};

// Literal class names so Tailwind generates each one. Uncertain is never green.
const STATE_TEXT: Record<LandslideRiskState, string> = {
  HIGH_RISK: "text-red-400",
  NOT_HIGH_RISK: "text-emerald-400",
  UNCERTAIN: "text-amber-400",
};

// The classifier's codes name its production inputs, not the Open-Meteo feed the estimate uses.
const REASON_LABEL: Record<string, string> = {
  FORECAST_UNAVAILABLE: "GFS forecast not connected",
  FORECAST_STALE: "GFS forecast stale",
  WEATHER_FEED_UNAVAILABLE: "Weather feed down",
  ESTIMATE_UNAVAILABLE: "No map value at this spot",
  ERA5_LAND_MISSING: "ERA5-Land missing",
  SMAP_MISSING: "SMAP missing",
  OUT_OF_DISTRIBUTION: "Outside the study area",
};

function reasonLabel(code: string): string {
  return REASON_LABEL[code] ?? humanize(code);
}

const EFFECT_GLYPH: Record<RiskEstimateDriver["effect"], { glyph: string; label: string }> = {
  raises: { glyph: "▲", label: "Raises the chance" },
  lowers: { glyph: "▼", label: "Lowers the chance" },
  neutral: { glyph: "–", label: "Little effect" },
};

/** 0.312 → "31%", 0.042 → "4.2%", 0.0004 → "<0.1%". */
function formatPercent(value: number): string {
  const percent = value * 100;
  if (percent < 0.1) return "<0.1%";
  if (percent < 9.95) return `${percent.toFixed(1)}%`;
  return `${Math.round(percent)}%`;
}

function formatCellSize(meters: number): string {
  return meters >= 1000 ? `${meters / 1000} km` : `${meters} m`;
}

function windowLabel(start: string, end: string): string {
  return `${formatUtc(start).replace(" UTC", "")}–${formatUtc(end)}`;
}

interface Settled {
  key: string;
  prediction: LandslideRiskPrediction | null;
  error: string | null;
}

/**
 * The landslide chance at the last map click. The headline is the calibrated probability when
 * the strict classifier has one, else the uncalibrated Model B estimate the heat map is drawn
 * from. The classifier's own state sits in the audit disclosure and is never shown as safe.
 */
export default function LandslideRiskCard({ latitude, longitude }: { latitude: number; longitude: number }) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);
  const key = `${latitude},${longitude},${attempt}`;
  const loading = settled?.key !== key;

  useEffect(() => {
    const controller = new AbortController();
    const requestKey = `${latitude},${longitude},${attempt}`;
    getLandslideRisk(latitude, longitude, undefined, { signal: controller.signal }).then(
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
  const level = prediction?.probability !== null ? (prediction?.risk_level ?? null) : null;

  return (
    <section
      aria-labelledby="cell-risk-heading"
      className={`border-t border-border px-5 py-4 ${level ? LEVEL_TREATMENT[level] : ""}`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="cell-risk-heading" className="text-sm text-muted-foreground">
          Landslide chance · next 72 hours
        </h2>
        {loading && settled && <span className="text-xs text-muted-foreground">Checking…</span>}
      </div>

      <div aria-live="polite" aria-busy={loading} className={loading && settled ? "opacity-50" : ""}>
        {!settled ? (
          <HeadlineSkeleton />
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
          prediction && <Headline prediction={prediction} />
        )}
      </div>

      <p className="mt-2 font-mono text-xs text-foreground">{formatLatLon(latitude, longitude)}</p>
      <p className="text-xs text-muted-foreground">Click anywhere on the map to check that spot.</p>

      {prediction && settled?.error === null && (
        <div className={`mt-3 space-y-3 text-sm ${loading ? "opacity-50" : ""}`}>
          <Source prediction={prediction} />
          {prediction.probability !== null && prediction.estimate && <EstimateDetails estimate={prediction.estimate} />}
          <ClassifierAudit prediction={prediction} />
        </div>
      )}
    </section>
  );
}

function HeadlineSkeleton() {
  return (
    <div className="mt-2 space-y-2" aria-label="Checking this spot">
      <div className="h-10 w-36 animate-work rounded-sm bg-muted motion-reduce:animate-none" />
      <div className="h-4 w-56 animate-work rounded-sm bg-muted motion-reduce:animate-none" />
    </div>
  );
}

function Headline({ prediction }: { prediction: LandslideRiskPrediction }) {
  const { probability, risk_level: level, reason_codes: reasons } = prediction;
  if (probability === null) {
    if (reasons.includes("OUT_OF_DISTRIBUTION")) {
      return <p className="mt-2 text-base">Outside the Mount Rainier study area. Click inside the mapped area.</p>;
    }
    if (reasons.includes("WEATHER_FEED_UNAVAILABLE")) {
      return (
        <p className="mt-2 text-base">
          Rain data is unavailable right now, so there is no estimate. A missing forecast is never treated as safe.
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
    <p className="mt-2 flex items-baseline gap-3">
      <span className={`font-mono text-4xl/10 font-semibold tracking-tight ${level ? LEVEL_TEXT[level] : ""}`}>
        {formatPercent(probability)}
      </span>
      {level && <LevelWord level={level} className="text-base font-semibold" />}
    </p>
  );
}

function Source({ prediction }: { prediction: LandslideRiskPrediction }) {
  if (prediction.probability_source === "calibrated_classifier") {
    return (
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Calibrated classifier</span> ·{" "}
        <span className={`font-semibold ${STATE_TEXT[prediction.state]}`}>{STATE_LABEL[prediction.state]}</span>
      </p>
    );
  }
  if (prediction.probability_source === "model_b_estimate") {
    return (
      <div className="text-xs text-muted-foreground">
        <p className="font-medium text-foreground">Model B estimate · uncalibrated</p>
        <p className="mt-0.5">
          The same model that colors the heat map: terrain susceptibility plus forecast and recent rain. Not a
          safety clearance.
        </p>
      </div>
    );
  }
  return null;
}

function EstimateDetails({ estimate }: { estimate: RiskEstimate }) {
  const { drivers, cell, rain } = estimate;
  return (
    <>
      {drivers.length > 0 && (
        <div>
          <h3 className="text-xs text-muted-foreground">Why</h3>
          <ul className="mt-1 space-y-1">
            {drivers.map((driver) => {
              const effect = EFFECT_GLYPH[driver.effect];
              return (
                <li key={driver.factor} className="flex items-baseline gap-2 text-xs">
                  <span role="img" aria-label={effect.label} className="w-3 shrink-0 text-muted-foreground">
                    {effect.glyph}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-wrap justify-between gap-x-3">
                    <span className="text-foreground">{driver.label}</span>
                    <span className="font-mono text-muted-foreground">{driver.detail}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {cell && (
        <p className="text-xs text-muted-foreground">
          {formatCellSize(cell.size_m)} cell: average <span className="font-mono text-foreground">{formatPercent(cell.mean)}</span>, peak{" "}
          <span className="font-mono text-foreground">{formatPercent(cell.max)}</span>,{" "}
          <span className="font-mono text-foreground">{formatPercent(cell.share_high)}</span> of it high or above
        </p>
      )}
      {rain && (
        <p className="text-xs text-muted-foreground">
          Rain from {rain.source === "open-meteo" ? "Open-Meteo" : humanize(rain.source)}, as of <span className="font-mono">{formatUtc(rain.as_of)}</span>
        </p>
      )}
    </>
  );
}

function ClassifierAudit({ prediction }: { prediction: LandslideRiskPrediction }) {
  const { state, confidence } = prediction;
  const percent = (value: number | null, digits: number) => (value === null ? "—" : `${(value * 100).toFixed(digits)}%`);
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-baseline gap-1.5 text-muted-foreground [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-primary group-open:rotate-90">▸</span>
        <span className="underline decoration-primary/60 decoration-1 underline-offset-3">Calibrated classifier:</span>
        <span className={`font-semibold ${STATE_TEXT[state]}`}>{STATE_LABEL[state]}</span>
      </summary>
      <div className="mt-2 space-y-2 text-muted-foreground">
        {state === "UNCERTAIN" && (
          <p className="rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-amber-200">
            The strict classifier abstains until it has calibrated artifacts and production forecast inputs. The
            estimate above is not a safety clearance.
          </p>
        )}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <span>Calibrated probability</span>
          <span className="text-right font-mono">{percent(prediction.calibrated_probability, 1)}</span>
          <span>Data quality</span>
          <span className="text-right font-mono">{percent(prediction.data_quality_score, 0)}</span>
          <span>OOD score</span>
          <span className="text-right font-mono">{prediction.ood_score === null ? "—" : prediction.ood_score.toFixed(2)}</span>
          <span>Window</span>
          <span className="text-right font-mono">
            {windowLabel(prediction.prediction_window.start, prediction.prediction_window.end)}
          </span>
          <span>Validated threshold</span>
          <span className="text-right font-mono">{percent(prediction.high_risk_threshold, 1)}</span>
          <span>Confidence</span>
          <span className="text-right font-mono">
            {confidence.lower === null || confidence.upper === null
              ? "—"
              : `${(confidence.lower * 100).toFixed(0)}–${(confidence.upper * 100).toFixed(0)}%`}
          </span>
        </div>
        {prediction.reason_codes.length > 0 && (
          <p>Reasons: {prediction.reason_codes.map(reasonLabel).join(" · ")}</p>
        )}
        {prediction.drivers.length > 0 && (
          <div>
            <p>Model risk drivers:</p>
            <ul className="mt-1 list-inside list-disc">
              {prediction.drivers.slice(0, 3).map((driver) => (
                <li key={driver.feature}>
                  {humanize(driver.feature)}
                  {driver.value !== null && <span className="font-mono"> ({driver.value.toFixed(2)})</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
