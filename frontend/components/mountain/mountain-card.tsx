"use client";

import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useMemo, useState } from "react";

/** Animates height to zero so content above agents can collapse without layout jumps. */
function Collapsible({ show, children }: { show: boolean; children: ReactNode }) {
  return (
    <div
      className={`grid transition-[grid-template-rows] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none ${
        show ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
      }`}
    >
      <div
        className={`min-h-0 overflow-hidden transition-opacity duration-300 ease-out motion-reduce:transition-none ${
          show ? "opacity-100" : "opacity-0"
        }`}
      >
        {children}
      </div>
    </div>
  );
}
import AgentPipeline from "@/components/pipeline/agent-pipeline";
import AnalyzeButton from "@/components/pipeline/analyze-button";
import SimulateButton from "@/components/pipeline/simulate-button";
import ResponsePlanModal from "@/components/pipeline/response-plan-modal";
import SimulationBar from "@/components/map/simulation-bar";
import LandslideRiskCard from "@/components/panel/landslide-risk-card";
import { getHillRiskSummary, getRiskSummary } from "@/lib/api";
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
}: MountainCardProps) {
  const [summary, setSummary] = useState(riskSummary);
  const hill = useMemo(() => buildMountainView(mountain, summary), [mountain, summary]);
  const hasRoutes = mountain.trails.some((trail) => (trail.geom?.coordinates?.length ?? 0) >= 2);
  const showPanelTabs = hasRoutes;
  const [focus, setFocus] = useState<CameraFocus | null>(null);
  const [tab, setTab] = useState<PanelTab>(() => (hasRoutes ? "prevention" : "response"));
  const [riskLocation, setRiskLocation] = useState({ latitude: mountain.lat, longitude: mountain.lon });
  const pipeline = usePipeline(hill);
  const finished = pipeline.state.orchestrator === "done";
  /** Response tab while a run is in flight or finished — collapses risk cards so agents fill the panel. */
  const agentsSessionActive =
    tab === "response" &&
    (pipeline.running ||
      pipeline.state.orchestrator === "running" ||
      pipeline.state.orchestrator === "done" ||
      pipeline.state.orchestrator === "error");
  const [planOpen, setPlanOpen] = useState(false);
  const [reanalyzeBanner, setReanalyzeBanner] = useState(false);
  const planReady = finished && pipeline.state.advisory != null && pipeline.state.measures != null;

  useEffect(() => {
    if (planReady) {
      setPlanOpen(true);
    }
  }, [planReady]);

  useEffect(() => {
    if (pipeline.running) {
      setReanalyzeBanner(false);
    }
  }, [pipeline.running]);

  // A finished run saves a new map, so the trail scores are read again.
  useEffect(() => {
    if (!finished || !mountain.is_live) return;
    const controller = new AbortController();
    const loadSummary =
      mountain.kind === "hill"
        ? getHillRiskSummary(mountain.slug, { signal: controller.signal })
        : getRiskSummary(mountain.slug, { signal: controller.signal });
    loadSummary.then(
      (next) => {
        if (!controller.signal.aborted) setSummary(next);
      },
      () => {},
    );
    return () => controller.abort();
  }, [finished, mountain.slug, mountain.is_live, mountain.kind]);
  useEffect(() => {
    if (!hasRoutes && tab !== "response") {
      setTab("response");
    }
  }, [hasRoutes, tab]);
  const simulation = useSimulation(mountain.slug);
  // MapLibre DOM markers can inflate document scrollHeight; lock the page while this view is open.
  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    const prevRoot = root.style.overflow;
    const prevBody = body.style.overflow;
    const prevOverscroll = root.style.overscrollBehavior;
    root.style.overflow = "hidden";
    body.style.overflow = "hidden";
    root.style.overscrollBehavior = "none";
    return () => {
      root.style.overflow = prevRoot;
      body.style.overflow = prevBody;
      root.style.overscrollBehavior = prevOverscroll;
    };
  }, []);
  const live = hill.isLive;
  /** Runout uses seeded trail geometry and Terrarium terrain when available (any peak or hill). */
  const simulationSupported = hasRoutes;
  const [simulateUnsupportedOpen, setSimulateUnsupportedOpen] = useState(false);
  const flowOn = simulation.phase === "playing" || simulation.phase === "finished";
  const flowField = simulation.simulation?.field ?? null;
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
    <main className="fixed inset-0 flex h-svh max-h-svh min-h-0 w-full animate-fade-in flex-col overflow-hidden motion-reduce:animate-none md:flex-row">
      <section
        aria-label="Mountain view"
        className="relative h-[42dvh] max-h-[50dvh] shrink-0 overflow-clip bg-muted md:h-full md:max-h-none md:min-h-0 md:w-[55%] md:min-w-0"
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
          flow={flowOn && !flowField ? (simulation.simulation?.frames[simulation.frameIndex]?.geojson ?? null) : null}
          flowField={flowOn ? flowField : null}
          playhead={simulation.playhead}
          flowActive={flowOn}
        />
        <SimulationBar phase={simulation.phase} simulation={simulation.simulation} timeS={simulation.timeS} />
      </section>

      <aside className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-border bg-card md:h-full md:w-[45%] md:min-w-0 md:flex-none md:border-l md:border-t-0">
        {reanalyzeBanner && (
          <div
            role="alert"
            className="flex shrink-0 items-start justify-between gap-3 border-b border-primary/25 bg-primary/10 px-5 py-2.5 text-sm text-foreground"
          >
            <p>
              Parameters changed — please click <span className="font-semibold">Analyze now</span> on the Agents
              page to refresh the plan.
            </p>
            <button
              type="button"
              onClick={() => setReanalyzeBanner(false)}
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )}
        <Collapsible show={!agentsSessionActive}>
          <div className="shrink-0">
            <MountainHeader hill={hill} />
            <OverallRisk hill={hill} />
            <LandslideRiskCard
              latitude={riskLocation.latitude}
              longitude={riskLocation.longitude}
              mountainSlug={mountain.slug}
              panelLayout="summary"
            />
          </div>
        </Collapsible>
        {showPanelTabs && <PanelTabs active={tab} onChange={setTab} />}
        <div
          className={`min-h-0 flex-1 overflow-y-auto overscroll-contain transition-[padding] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none ${
            agentsSessionActive ? "flex flex-col" : ""
          }`}
        >
          <TabPanel tab="prevention" active={tab}>
            {hill.trails.length > 0 && (
              <TrailList
                trails={hill.trails}
                selected={selected}
                onView={view}
                variant={hill.scoring ? "risk" : "mapped"}
              />
            )}
            {live && (
              <LandslideRiskCard
                latitude={riskLocation.latitude}
                longitude={riskLocation.longitude}
                mountainSlug={mountain.slug}
                panelLayout="detailsOnly"
              />
            )}
          </TabPanel>
          <TabPanel tab="response" active={tab} fill={agentsSessionActive}>
            <section
              id="agents"
              aria-labelledby="agents-heading"
              className={`border-t border-border px-5 transition-[padding,flex-grow] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none ${
                agentsSessionActive ? "flex min-h-0 flex-1 flex-col border-t-0 py-5 md:py-6" : "py-4"
              }`}
            >
              {!agentsSessionActive && (
                <h2 id="agents-heading" className="text-sm text-muted-foreground">
                  Agents
                </h2>
              )}
              {agentsSessionActive && (
                <h2 id="agents-heading" className="sr-only">
                  Agents
                </h2>
              )}
              <div className={`${agentsSessionActive ? "min-h-0 flex-1" : "mt-2"}`}>
                <AgentPipeline state={pipeline.state} expandedLayout={agentsSessionActive} />
              </div>
            </section>
            {!agentsSessionActive && planReady && (
              <section className="border-t border-border px-5 py-4">
                <button
                  type="button"
                  onClick={() => setPlanOpen(true)}
                  className="w-full rounded-md border border-primary/40 bg-primary/10 px-4 py-3 text-left text-sm font-semibold text-foreground hover:bg-primary/15"
                >
                  View response plan
                  <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                    Priority actions from the agent run — not sent until you approve
                  </span>
                </button>
              </section>
            )}
            {agentsSessionActive && planReady && (
              <section className="shrink-0 border-t border-border px-5 py-3">
                <button
                  type="button"
                  onClick={() => setPlanOpen(true)}
                  className="w-full rounded-md bg-primary/15 px-4 py-2.5 text-sm font-semibold text-foreground hover:bg-primary/20"
                >
                  View response plan
                </button>
              </section>
            )}
            {!agentsSessionActive && live && pipeline.state.orchestrator === "done" && hill.preventative.length > 0 && (
              <PreventativeMeasures items={hill.preventative} />
            )}
            {!agentsSessionActive && !live && (
              <LandslideRiskCard
                latitude={riskLocation.latitude}
                longitude={riskLocation.longitude}
                mountainSlug={mountain.slug}
                panelLayout="full"
              />
            )}
          </TabPanel>
        </div>
        <footer className="shrink-0 border-t border-border bg-card px-5 py-4">
          {tab === "prevention" ? (
            hasRoutes ? (
              <>
                <div className="flex">
                  <SimulateButton
                    phase={simulationSupported ? simulation.phase : "idle"}
                    onSimulate={handleSimulate}
                    onReplay={handleSimulate}
                  />
                </div>
                {simulationSupported && simulation.error && (
                  <p className="mt-2 text-sm text-foreground">{simulation.error}</p>
                )}
              </>
            ) : null
          ) : (
            <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} />
          )}
        </footer>
        <SimulationUnsupportedDialog
          open={simulateUnsupportedOpen}
          placeName={mountain.name}
          analyzeAvailable={live}
          onClose={() => setSimulateUnsupportedOpen(false)}
        />
        {planReady && pipeline.state.advisory && pipeline.state.measures && (
          <ResponsePlanModal
            open={planOpen}
            hill={hill}
            advisory={pipeline.state.advisory}
            measures={pipeline.state.measures}
            pipeline={pipeline.state}
            onClose={() => setPlanOpen(false)}
            onRevise={() => {
              setPlanOpen(false);
              setReanalyzeBanner(true);
              setTab("response");
            }}
          />
        )}
      </aside>
    </main>
  );
}

/** One tab's section. Every tab stays mounted, so its scroll, fetches, and open traces survive a switch. */
function TabPanel({
  tab,
  active,
  fill,
  children,
}: {
  tab: PanelTab;
  active: PanelTab;
  fill?: boolean;
  children: ReactNode;
}) {
  if (tab !== active) {
    return null;
  }
  return (
    <div
      role="tabpanel"
      id={tabPanelId(tab)}
      aria-labelledby={tabId(tab)}
      className={`[&>section:first-child]:border-t-0 ${fill ? "flex min-h-0 flex-1 flex-col" : ""}`}
    >
      {children}
    </div>
  );
}
