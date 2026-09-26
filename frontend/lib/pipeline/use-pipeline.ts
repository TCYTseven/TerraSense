"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MountainView, PipelineState } from "../mountain-view";
import { runLiveAnalysis } from "./live-run";
import { initialPipelineState } from "./orchestrator";

export interface PipelineControls {
  state: PipelineState;
  /** True from the click until the orchestrator finishes or fails. */
  running: boolean;
  /** Starts a run. Does nothing while one is running. */
  analyze: () => void;
}

/**
 * Holds the pipeline's state and runs it on demand. Every mountain calls the API.
 * A summit with no trails still runs: the agents use its location, the risk model, and the weather.
 */
export function usePipeline(hill: MountainView, enabled = true): PipelineControls {
  const [state, setState] = useState<PipelineState>(initialPipelineState);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const analyze = useCallback(() => {
    if (!enabled || busy.current) return;
    busy.current = true;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setState(initialPipelineState());
    setRunning(true);
    const run = runLiveAnalysis(hill.slug, setState, next.signal);
    run.finally(() => {
      if (next.signal.aborted) return;
      busy.current = false;
      setRunning(false);
    });
  }, [enabled, hill]);

  // Stop the run when the card unmounts.
  useEffect(
    () => () => {
      controller.current?.abort();
      busy.current = false;
    },
    [],
  );

  return { state, running, analyze };
}
