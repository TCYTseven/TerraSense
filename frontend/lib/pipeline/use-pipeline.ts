"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { HillView, PipelineState } from "../hill";
import { runLiveAnalysis } from "./live-run";
import { initialPipelineState, runPipeline } from "./orchestrator";

export interface PipelineControls {
  state: PipelineState;
  /** True from the click until the orchestrator finishes or fails. */
  running: boolean;
  /** Starts a run. Does nothing while one is running. */
  analyze: () => void;
}

/**
 * Holds the pipeline's state and runs it on demand. A live mountain calls the API, which
 * uses the Gemini or xAI key in the repo root .env. Anything else stays on the scripted demo.
 */
export function usePipeline(hill: HillView): PipelineControls {
  const [state, setState] = useState<PipelineState>(initialPipelineState);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const analyze = useCallback(() => {
    if (busy.current) return;
    busy.current = true;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setState(initialPipelineState());
    setRunning(true);
    const run = hill.isLive ? runLiveAnalysis(hill.slug, setState, next.signal) : runPipeline(hill, setState, next.signal);
    run.finally(() => {
      if (next.signal.aborted) return;
      busy.current = false;
      setRunning(false);
    });
  }, [hill]);

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
