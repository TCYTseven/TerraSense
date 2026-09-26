"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import AgentPipeline from "@/components/pipeline/agent-pipeline";
import AnalyzeButton from "@/components/pipeline/analyze-button";
import ReactiveMeasures from "@/components/pipeline/reactive-measures";
import { buildHillView } from "@/lib/fixtures/hill-demo";
import type { CameraFocus, TrailLetter } from "@/lib/hill";
import { usePipeline } from "@/lib/pipeline/use-pipeline";
import type { LayerTiles, MountainDetail } from "@/lib/types";
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
}

/**
 * The hill detail card: the 3D mountain on the left, one scrollable stats panel on the right
 * with the Analyze button pinned under it. "View" on a trail row flies the camera to its marker.
 */
export default function HillCard({ mountain, probability, susceptibility }: HillCardProps) {
  const hill = useMemo(() => buildHillView(mountain), [mountain]);
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const pipeline = usePipeline(hill);
  const live = hill.isLive;

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
        />
      </section>

      <aside className="flex min-h-0 flex-col border-t border-border bg-card md:w-[45%] md:border-l md:border-t-0">
        <div className="min-h-0 flex-1 md:overflow-y-auto">
          <HillHeader hill={hill} />
          <OverallRisk hill={hill} />
          {live && hill.trails.length > 0 && (
            <TrailList trails={hill.trails} selected={focus?.letter ?? null} onView={view} />
          )}
          {live && hill.preventative.length > 0 && <PreventativeMeasures items={hill.preventative} />}
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
          {live && pipeline.state.orchestrator === "done" && pipeline.state.measures && (
            <ReactiveMeasures measures={pipeline.state.measures} level={hill.risk.level} trails={hill.trails} />
          )}
        </div>
        {live && (
          <footer className="border-t border-border bg-card px-5 py-4">
            <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} />
          </footer>
        )}
      </aside>
    </main>
  );
}
