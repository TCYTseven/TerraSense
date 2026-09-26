"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import AgentPipeline from "@/components/pipeline/agent-pipeline";
import AnalyzeButton from "@/components/pipeline/analyze-button";
import ReactiveMeasures from "@/components/pipeline/reactive-measures";
import HazardBlock from "@/components/panel/hazard-block";
import HikerCard, { type HikerCardState } from "@/components/panel/hiker-card";
import LandslideRiskCard from "@/components/panel/landslide-risk-card";
import { getForecast } from "@/lib/api";
import type { CameraFocus, TrailLetter } from "@/lib/hill";
import { buildHillView } from "@/lib/hill-view";
import { usePipeline } from "@/lib/pipeline/use-pipeline";
import type { LayerTiles, MountainDetail, TrailRiskView } from "@/lib/types";
import HillHeader from "./hill-header";
import OverallRisk from "./overall-risk";
import PreventativeMeasures from "./preventative-measures";
import TrailList from "./trail-list";

// The 3D view needs WebGL and the DOM, so it renders in the browser only.
const HillMountainView = dynamic(() => import("@/components/map/hill-mountain-view"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-muted" />,
});

export interface HillCardProps {
  mountain: MountainDetail;
  probability: LayerTiles | null;
  susceptibility: LayerTiles | null;
  /** The top trails on the current map. Null for static mountains or when the API did not answer. */
  trailRisk: TrailRiskView | null;
}

/**
 * The hill detail card: the 3D mountain on the left, one scrollable stats panel on the right
 * with the Analyze button pinned under it. "View" on a trail row flies the camera to its marker.
 */
export default function HillCard({ mountain, probability, susceptibility, trailRisk }: HillCardProps) {
  const router = useRouter();
  const hill = useMemo(() => buildHillView(mountain, trailRisk), [mountain, trailRisk]);
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const [riskLocation, setRiskLocation] = useState({ latitude: mountain.lat, longitude: mountain.lon });
  const [hazardOpen, setHazardOpen] = useState(false);
  const [hiker, setHiker] = useState<HikerCardState | null>(null);
  // A finished run wrote new tiles, a new hazard, and new trail scores: reload the server data.
  const pipeline = usePipeline(hill, { activeRunId: mountain.active_run_id, onLiveRunDone: () => router.refresh() });
  const live = hill.isLive;
  const hazard = mountain.active_hazard;
  const finished = pipeline.state.orchestrator === "done";

  function view(letter: TrailLetter) {
    setFocus({ letter, nonce: Date.now() });
  }

  function openHiker() {
    setHiker({ kind: "loading" });
    getForecast(mountain.slug)
      .then((forecast) => setHiker(forecast ? { kind: "ready", forecast } : { kind: "error" }))
      .catch(() => setHiker({ kind: "error" }));
  }

  return (
    <main className="flex min-h-dvh animate-fade-in flex-col motion-reduce:animate-none md:h-dvh md:flex-row">
      <section
        aria-label="Mountain view"
        className="relative h-[55dvh] shrink-0 overflow-hidden bg-muted md:h-auto md:w-[55%]"
      >
        <HillMountainView
          key={mountain.slug}
          mountain={mountain}
          probability={probability}
          susceptibility={susceptibility}
          trails={hill.trails}
          focus={focus}
          onTrailSelect={view}
          onMapClick={setRiskLocation}
          hazardSelected={hazardOpen}
          onHazardClick={() => setHazardOpen((open) => !open)}
          bypass={hiker?.kind === "ready" ? hiker.forecast.bypass : null}
        />
      </section>

      <aside className="flex min-h-0 flex-col border-t border-border bg-card md:w-[45%] md:border-l md:border-t-0">
        {hiker ? (
          <div className="min-h-0 flex-1 md:overflow-y-auto">
            <HikerCard state={hiker} onBack={() => setHiker(null)} />
          </div>
        ) : (
          <div className="min-h-0 flex-1 md:overflow-y-auto">
            <HillHeader hill={hill} />
            <OverallRisk hill={hill} />
            {live && hazardOpen && hazard && <HazardBlock hazard={hazard} onClose={() => setHazardOpen(false)} />}
            {live && (
              <LandslideRiskCard
                key={`${riskLocation.latitude},${riskLocation.longitude}`}
                latitude={riskLocation.latitude}
                longitude={riskLocation.longitude}
              />
            )}
            {live && hill.trails.length > 0 && (
              <TrailList trails={hill.trails} selected={focus?.letter ?? null} onView={view} />
            )}
            {live && (
              <section id="agents" aria-labelledby="agents-heading" className="border-t border-border px-5 py-4">
                <h2 id="agents-heading" className="text-sm text-muted-foreground">
                  Agents
                </h2>
                <div className="mt-2">
                  <AgentPipeline state={pipeline.state} />
                </div>
              </section>
            )}
            {live && finished && pipeline.state.measures && (
              <ReactiveMeasures
                measures={pipeline.state.measures}
                level={pipeline.state.advisory?.severity ?? hill.risk.level}
                trails={hill.trails}
              />
            )}
            {live && finished && hill.preventative.length > 0 && <PreventativeMeasures items={hill.preventative} />}
            {live && finished && pipeline.state.advisory && hazard && (
              <div className="border-t border-border px-5 py-4">
                <button
                  type="button"
                  onClick={openHiker}
                  className="text-base text-primary underline decoration-1 underline-offset-3"
                >
                  Open the hiker view
                </button>
              </div>
            )}
          </div>
        )}
        {live && !hiker && (
          <footer className="border-t border-border bg-card px-5 py-4">
            <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} />
          </footer>
        )}
      </aside>
    </main>
  );
}
