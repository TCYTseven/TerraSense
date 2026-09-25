"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import MountainMap from "@/components/map/mountain-map";
import { rowStates } from "@/components/panel/agent-rows";
import RangerPanel from "@/components/panel/ranger-panel";
import ReasoningPanel from "@/components/panel/reasoning-panel";
import { ApiError, getLayer, getMountain, startAnalysis } from "@/lib/api";
import { formatClock } from "@/lib/format";
import { followRun } from "@/lib/run-stream";
import type { AgentName, LayerTiles, MountainDetail, Run } from "@/lib/types";

export interface MountainDashboardProps {
  mountain: MountainDetail;
  probability: LayerTiles | null;
  susceptibility: LayerTiles | null;
  /** The run the rows start with: one going now, or the one behind the active hazard. */
  run: Run | null;
  /** Open the hazard at load, as the Discord link does. */
  openHazard: boolean;
}

type Problem = { kind: "lost" } | { kind: "start"; detail: string } | { kind: "reload" } | null;

/**
 * The mountain page's live state: the map, the ranger panel, a run in progress, and the
 * reasoning side panel. Analyze now starts a run and follows its stream; a finished run reloads
 * the mountain and its heat map and opens the new hazard. A failed run leaves the last good one.
 */
export default function MountainDashboard(props: MountainDashboardProps) {
  const [mountain, setMountain] = useState(props.mountain);
  const [probability, setProbability] = useState(props.probability);
  const [run, setRun] = useState<Run | null>(props.run);
  // The run this page started or joined: its status line reads as news, not history.
  const [followedHere, setFollowedHere] = useState<string | null>(props.mountain.active_run_id);
  const [hazardOpen, setHazardOpen] = useState(props.openHazard && Boolean(props.mountain.active_hazard));
  const [reasoning, setReasoning] = useState<AgentName | null>(null);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const stop = useRef<(() => void) | null>(null);
  const slug = mountain.slug;

  const reload = useCallback(async () => {
    try {
      const [nextMountain, nextProbability] = await Promise.all([getMountain(slug), getLayer(slug, "probability")]);
      if (nextMountain) {
        setMountain(nextMountain);
        setHazardOpen(Boolean(nextMountain.active_hazard));
      }
      setProbability(nextProbability);
    } catch {
      setProblem({ kind: "reload" });
    }
  }, [slug]);

  const follow = useCallback(
    (runId: string) => {
      stop.current?.();
      stop.current = followRun(runId, {
        onRun: (next) => {
          setRun(next);
          if (next.status === "done") {
            void reload();
          }
        },
        onEvent: (event) =>
          setRun((current) =>
            current && current.id === event.run_id
              ? { ...current, agents: { ...current.agents, [event.agent]: event } }
              : current,
          ),
        onLost: () => setProblem({ kind: "lost" }),
      });
    },
    [reload],
  );

  // A run that was going when the page opened: follow it.
  const activeAtOpen = props.mountain.active_run_id;
  useEffect(() => {
    if (activeAtOpen) {
      follow(activeAtOpen);
    }
    return () => stop.current?.();
  }, [activeAtOpen, follow]);

  async function analyze() {
    setStarting(true);
    setProblem(null);
    // The five rows are the moment to watch: bring them into view, at once (no smooth scroll).
    document.getElementById("agents")?.scrollIntoView({ block: "nearest" });
    try {
      const runId = await startAnalysis(slug);
      setFollowedHere(runId);
      follow(runId);
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : "The API did not answer.";
      setProblem({ kind: "start", detail });
    } finally {
      setStarting(false);
    }
  }

  const hazard = mountain.active_hazard;
  const rows = rowStates(run);
  const running = run?.status === "running" && problem?.kind !== "lost";
  const stillShows = hazard
    ? `The map still shows the hazard from ${formatClock(hazard.created_at)}.`
    : "There's no earlier hazard to show.";
  let status: string | null = null;
  if (problem?.kind === "lost") {
    status = `Lost the connection to this run. ${stillShows}`;
  } else if (problem?.kind === "start") {
    status = `Could not start the analysis. ${problem.detail}`;
  } else if (problem?.kind === "reload") {
    status = "The run finished, but the map could not reload. Reload the page to see it.";
  } else if (run && run.status !== "running") {
    if (run.id !== followedHere) {
      status = run.finished_at ? `Last run finished at ${formatClock(run.finished_at)}.` : null;
    } else {
      status = run.status === "error" ? `${run.message} ${stillShows}` : run.message;
    }
  }

  return (
    <main className="flex min-h-dvh animate-fade-in flex-col motion-reduce:animate-none md:h-dvh md:flex-row">
      <section aria-label="Terrain map" className="relative h-[55dvh] shrink-0 overflow-hidden bg-muted md:h-auto md:flex-1">
        <MountainMap
          key={mountain.slug}
          name={mountain.name}
          lon={mountain.lon}
          lat={mountain.lat}
          elevationM={mountain.elevation_m}
          trails={mountain.trails}
          isLive={mountain.is_live}
          probability={probability}
          susceptibility={props.susceptibility}
          hazard={hazard}
          hazardSelected={hazardOpen}
          onHazardClick={() => setHazardOpen((open) => !open)}
          onMapClick={() => setHazardOpen(false)}
          historicalEvents={mountain.historical_events}
        />
        {reasoning && (
          <ReasoningPanel
            run={run}
            rows={rows}
            agent={reasoning}
            onAgent={setReasoning}
            onClose={() => setReasoning(null)}
          />
        )}
      </section>
      <RangerPanel
        mountain={mountain}
        hazard={hazard}
        hazardOpen={hazardOpen}
        onCloseHazard={() => setHazardOpen(false)}
        run={run}
        rows={rows}
        analyzing={starting || running}
        status={status}
        heatMapIsStandIn={probability?.method?.includes("stand-in") ?? false}
        onAnalyze={analyze}
        onOpenReasoning={setReasoning}
      />
    </main>
  );
}
