"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import AgentPipeline from "@/components/pipeline/agent-pipeline";
import AnalyzeButton from "@/components/pipeline/analyze-button";
import SimulateButton from "@/components/pipeline/simulate-button";
import ReactiveMeasures from "@/components/pipeline/reactive-measures";
import SimulationBar from "@/components/map/simulation-bar";
import LandslideRiskCard from "@/components/panel/landslide-risk-card";
import { getRiskSummary } from "@/lib/api";
import { buildHillView } from "@/lib/hill-view";
import type { CameraFocus, TrailLetter } from "@/lib/hill";
import { usePipeline } from "@/lib/pipeline/use-pipeline";
import { useSimulation } from "@/lib/use-simulation";
import type { LayerTiles, MountainDetail, MountainRiskSummary } from "@/lib/types";
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
  /** The trail scores on the saved heat map at page load. Null before the first save. */
  riskSummary: MountainRiskSummary | null;
}

/**
 * The hill detail card: the 3D mountain on the left, one scrollable stats panel on the right
 * with the Analyze button pinned under it. "View" on a trail row flies the camera to its marker.
 */
export default function HillCard({ mountain, probability, susceptibility, riskSummary }: HillCardProps) {
  const [summary, setSummary] = useState(riskSummary);
  const hill = useMemo(() => buildHillView(mountain, summary), [mountain, summary]);
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const [riskLocation, setRiskLocation] = useState({ latitude: mountain.lat, longitude: mountain.lon });
  const pipeline = usePipeline(hill);
  const finished = pipeline.state.orchestrator === "done";

  // A finished run saves a new map, so the trail scores are read again.
  useEffect(() => {
    if (!finished || !mountain.is_live) return;
    const controller = new AbortController();
    getRiskSummary(mountain.slug, { signal: controller.signal }).then(
      (next) => {
        if (!controller.signal.aborted) setSummary(next);
      },
      () => {},
    );
    return () => controller.abort();
  }, [finished, mountain.slug, mountain.is_live]);
  const simulation = useSimulation(mountain.slug);
  const live = hill.isLive;
  const hasRoutes = mountain.trails.length > 0;
  const flowOn = simulation.phase === "playing" || simulation.phase === "finished";
  const matched = hill.trails.find((trail) => trail.name === simulation.simulation?.pressure_point?.trail_name);
  const selected =
    focus && simulation.camera && focus.nonce > simulation.camera.nonce
      ? focus.letter
      : (matched?.letter ?? focus?.letter ?? null);

  function view(letter: TrailLetter) {
    setFocus({ letter, nonce: Date.now() });
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
          release={simulation.camera}
          flow={flowOn ? (simulation.simulation?.frames[simulation.frameIndex]?.geojson ?? null) : null}
          flowActive={flowOn}
        />
        <SimulationBar phase={simulation.phase} simulation={simulation.simulation} timeS={simulation.timeS} />
      </section>

      <aside className="flex min-h-0 flex-col border-t border-border bg-card md:w-[45%] md:border-l md:border-t-0">
        <div className="min-h-0 flex-1 md:overflow-y-auto">
          <HillHeader hill={hill} />
          <OverallRisk hill={hill} />
          {live && <LandslideRiskCard latitude={riskLocation.latitude} longitude={riskLocation.longitude} />}
          {live && hill.trails.length > 0 && (
            <TrailList trails={hill.trails} selected={selected} onView={view} />
          )}
          <section id="agents" aria-labelledby="agents-heading" className="border-t border-border px-5 py-4">
            <h2 id="agents-heading" className="text-sm text-muted-foreground">
              Agents
            </h2>
            <div className="mt-2">
              <AgentPipeline state={pipeline.state} />
            </div>
          </section>
          {pipeline.state.orchestrator === "done" && pipeline.state.measures && (
            <ReactiveMeasures measures={pipeline.state.measures} level={hill.risk.level} trails={hill.trails} />
          )}
          {live && pipeline.state.orchestrator === "done" && hill.preventative.length > 0 && (
            <PreventativeMeasures items={hill.preventative} />
          )}
        </div>
        {(live || hasRoutes) && (
          <footer className="border-t border-border bg-card px-5 py-4">
            <div className={hasRoutes && live ? "flex gap-2" : undefined}>
              {hasRoutes && (
                <SimulateButton phase={simulation.phase} onSimulate={simulation.start} onReplay={simulation.replay} />
              )}
              {live && <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} className={hasRoutes ? "flex-1" : undefined} />}
            </div>
            {simulation.error && <p className="mt-2 text-sm text-foreground">{simulation.error}</p>}
          </footer>
        )}
      </aside>
    </main>
  );
}
