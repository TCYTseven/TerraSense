"use client";

import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import AgentPipeline from "@/components/pipeline/agent-pipeline";
import AnalyzeButton from "@/components/pipeline/analyze-button";
import SimulateButton from "@/components/pipeline/simulate-button";
import ReactiveMeasures from "@/components/pipeline/reactive-measures";
import SimulationBar from "@/components/map/simulation-bar";
import LandslideRiskCard from "@/components/panel/landslide-risk-card";
import { getRiskSummary } from "@/lib/api";
import { buildMountainView } from "@/lib/mountain-view-build";
import type { CameraFocus, TrailLetter } from "@/lib/mountain-view";
import { usePipeline } from "@/lib/pipeline/use-pipeline";
import { useSimulation } from "@/lib/use-simulation";
import type { LayerTiles, MountainDetail, MountainRiskSummary } from "@/lib/types";
import MountainHeader from "./mountain-header";
import OverallRisk from "./overall-risk";
import PanelTabs, { type PanelTab, tabId, tabPanelId } from "./panel-tabs";
import PreventativeMeasures from "./preventative-measures";
import SimulationUnsupportedDialog from "./simulation-unsupported-dialog";
import TrailList from "./trail-list";

// The 3D view needs WebGL and the DOM, so it renders in the browser only.
const MountainTerrainView = dynamic(() => import("@/components/map/mountain-terrain-view"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-muted" />,
});

export interface MountainCardProps {
  mountain: MountainDetail;
  probability: LayerTiles | null;
  susceptibility: LayerTiles | null;
  /** The trail scores on the saved heat map at page load. Null before the first save. */
  riskSummary: MountainRiskSummary | null;
  /**
   * When false, the Agents block stays idle, Analyze now is not rendered, and nothing
   * starts a run. A hill page sets this. Simulate still appears when the place has routes.
   */
  orchestration?: boolean;
}

/**
 * The mountain page: the 3D mountain on the left, the stats panel on the right. The header and
 * overall risk stay at the top; under them two tabs, Prevention (Simulate pinned under it) and
 * Response (Analyze pinned under it). "View" on a trail row flies the camera to its marker.
 */
export default function MountainCard({
  mountain,
  probability,
  susceptibility,
  riskSummary,
  orchestration = true,
}: MountainCardProps) {
  const [summary, setSummary] = useState(riskSummary);
  const hill = useMemo(() => buildMountainView(mountain, summary), [mountain, summary]);
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const [tab, setTab] = useState<PanelTab>("prevention");
  const [riskLocation, setRiskLocation] = useState({ latitude: mountain.lat, longitude: mountain.lon });
  const pipeline = usePipeline(hill, orchestration);
  const finished = pipeline.state.orchestrator === "done";

  // A finished run saves a new map, so the trail scores are read again.
  useEffect(() => {
    if (!orchestration || !finished || !mountain.is_live) return;
    const controller = new AbortController();
    getRiskSummary(mountain.slug, { signal: controller.signal }).then(
      (next) => {
        if (!controller.signal.aborted) setSummary(next);
      },
      () => {},
    );
    return () => controller.abort();
  }, [finished, mountain.slug, mountain.is_live, orchestration]);
  const simulation = useSimulation(mountain.slug);
  const live = hill.isLive;
  const hasRoutes = mountain.trails.length > 0;
  /** Runout simulation needs a prepared pack and trail geometry (demo peaks only). */
  const simulationSupported = live && hasRoutes;
  const [simulateUnsupportedOpen, setSimulateUnsupportedOpen] = useState(false);
  const flowOn = simulation.phase === "playing" || simulation.phase === "finished";
  const matched = hill.trails.find((trail) => trail.name === simulation.simulation?.pressure_point?.trail_name);
  const selected =
    focus && simulation.camera && focus.nonce > simulation.camera.nonce
      ? focus.letter
      : (matched?.letter ?? focus?.letter ?? null);

  function view(letter: TrailLetter) {
    setFocus({ letter, nonce: Date.now() });
    // A trail picked on the map shows its row.
    setTab("prevention");
  }

  function handleSimulate() {
    if (!simulationSupported) {
      setSimulateUnsupportedOpen(true);
      return;
    }
    if (simulation.phase === "finished") {
      simulation.replay();
    } else {
      simulation.start();
    }
  }

  return (
    <main className="flex h-dvh max-h-dvh animate-fade-in flex-col overflow-hidden motion-reduce:animate-none md:flex-row">
      <section
        aria-label="Mountain view"
        className="relative h-[42dvh] max-h-[50dvh] shrink-0 overflow-hidden bg-muted md:h-auto md:max-h-none md:min-h-0 md:w-[55%]"
      >
        <MountainTerrainView
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

      <aside className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-border bg-card md:w-[45%] md:flex-none md:border-l md:border-t-0">
        <div className="shrink-0">
          <MountainHeader hill={hill} />
          <OverallRisk hill={hill} mappedTrails={mountain.trails.length} />
        </div>
        <PanelTabs active={tab} onChange={setTab} />
        <TabPanel tab="prevention" active={tab}>
          {live && <LandslideRiskCard latitude={riskLocation.latitude} longitude={riskLocation.longitude} />}
          {hill.trails.length > 0 && (
            <TrailList
              trails={hill.trails}
              selected={selected}
              onView={view}
              variant={hill.scoring ? "risk" : "mapped"}
            />
          )}
          {hill.trails.length === 0 && mountain.trails.length === 0 && (
            <p className="px-5 py-4 text-base text-muted-foreground">No trails are mapped here.</p>
          )}
        </TabPanel>
        <TabPanel tab="response" active={tab}>
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
        </TabPanel>
        {(tab === "prevention" ? orchestration || hasRoutes : orchestration) && (
        <footer className="shrink-0 border-t border-border bg-card px-5 py-4">
          {/* Each tab pins its own action. A hill with no routes has neither. */}
          {tab === "prevention" ? (
            <div className="flex">
              <SimulateButton
                phase={simulationSupported ? simulation.phase : "idle"}
                onSimulate={handleSimulate}
                onReplay={handleSimulate}
              />
            </div>
          ) : (
            <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} />
          )}
          {tab === "prevention" && simulationSupported && simulation.error && (
            <p className="mt-2 text-sm text-foreground">{simulation.error}</p>
          )}
        </footer>
        )}
        <SimulationUnsupportedDialog
          open={simulateUnsupportedOpen}
          mountainName={mountain.name}
          onClose={() => setSimulateUnsupportedOpen(false)}
        />
      </aside>
    </main>
  );
}

/** One tab's section. Every tab stays mounted, so its scroll, fetches, and open traces survive a switch. */
function TabPanel({ tab, active, children }: { tab: PanelTab; active: PanelTab; children: ReactNode }) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId(tab)}
      aria-labelledby={tabId(tab)}
      hidden={tab !== active}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain [&>section:first-child]:border-t-0"
    >
      {children}
    </div>
  );
}
