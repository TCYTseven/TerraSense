"use client";

import { useEffect, useState } from "react";
import { getLandslideRisk } from "@/lib/api";
import type { LandslideRiskPrediction, LandslideRiskState } from "@/lib/types";

function stateLabel(state: LandslideRiskState): string {
  return state === "HIGH_RISK" ? "High risk" : state === "NOT_HIGH_RISK" ? "Not high risk" : "Uncertain";
}

function stateClass(state: LandslideRiskState): string {
  return state === "HIGH_RISK"
    ? "text-red-600"
    : state === "NOT_HIGH_RISK"
      ? "text-emerald-600"
      : "text-amber-600";
}

function reasonLabel(code: string): string {
  return code
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function windowLabel(start: string, end: string): string {
  const format = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC" });
  return `${format.format(new Date(start))}–${format.format(new Date(end))} UTC`;
}

/** The calibrated cell-level classifier, separate from the legacy trail/raster score. */
export default function LandslideRiskCard({ latitude, longitude }: { latitude: number; longitude: number }) {
  const [prediction, setPrediction] = useState<LandslideRiskPrediction | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const result = await getLandslideRisk(latitude, longitude, undefined, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setPrediction(result);
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Risk classification unavailable");
        }
      }
    }
    void load();
    return () => controller.abort();
  }, [latitude, longitude]);

  return (
    <section aria-labelledby="cell-risk-heading" className="border-t border-border px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="cell-risk-heading" className="text-sm text-muted-foreground">
          72-hour cell classification
        </h2>
        {prediction && <span className={`text-xs font-semibold ${stateClass(prediction.state)}`}>{stateLabel(prediction.state)}</span>}
      </div>
      {error && <p className="mt-2 text-sm text-muted-foreground">Classification unavailable: {error}</p>}
      {!error && !prediction && <p className="mt-2 text-sm text-muted-foreground">Checking calibrated model and data freshness…</p>}
      {prediction && (
        <div className="mt-2 space-y-2 text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <span>Calibrated probability</span>
            <span className="font-mono font-semibold">
              {prediction.calibrated_probability === null ? "—" : `${(prediction.calibrated_probability * 100).toFixed(1)}%`}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>Data quality</span><span className="text-right font-mono">{(prediction.data_quality_score * 100).toFixed(0)}%</span>
            <span>OOD score</span><span className="text-right font-mono">{prediction.ood_score === null ? "—" : prediction.ood_score.toFixed(2)}</span>
            <span>Window</span><span className="text-right font-mono">{windowLabel(prediction.prediction_window.start, prediction.prediction_window.end)}</span>
            <span>Validated threshold</span><span className="text-right font-mono">{prediction.high_risk_threshold === null ? "—" : `${(prediction.high_risk_threshold * 100).toFixed(1)}%`}</span>
            <span>Confidence</span><span className="text-right font-mono">
              {prediction.confidence.lower === null || prediction.confidence.upper === null
                ? "—"
                : `${(prediction.confidence.lower * 100).toFixed(0)}–${(prediction.confidence.upper * 100).toFixed(0)}%`}
            </span>
          </div>
          {prediction.state === "UNCERTAIN" && (
            <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-700">
              This cell is not classified as safe or high risk because the evidence or model support is insufficient.
            </p>
          )}
          {prediction.reason_codes.length > 0 && (
            <p className="text-xs text-muted-foreground">Why: {prediction.reason_codes.map(reasonLabel).join(" · ")}</p>
          )}
          {prediction.drivers.length > 0 && (
            <div className="text-xs text-muted-foreground">
              <p>Model risk drivers:</p>
              <ul className="mt-1 list-inside list-disc">
                {prediction.drivers.slice(0, 3).map((driver) => (
                  <li key={driver.feature}>
                    {reasonLabel(driver.feature)}{driver.value === null ? "" : ` (${driver.value.toFixed(2)})`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
