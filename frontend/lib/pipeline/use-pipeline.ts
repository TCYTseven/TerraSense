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
export interface PipelineOptions {
  /** A run already going when the page opened. The card follows it instead of sitting idle. */
  activeRunId?: string | null;
  /** Called once a live run finishes, so the page can reload the map and trails it wrote. */
  onLiveRunDone?: () => void;
}

export function usePipeline(hill: HillView, options: PipelineOptions = {}): PipelineControls {
  const [state, setState] = useState<PipelineState>(initialPipelineState);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const onLiveRunDone = useRef(options.onLiveRunDone);
  // The latest callback without restarting anything when the parent re-renders.
  useEffect(() => {
    onLiveRunDone.current = options.onLiveRunDone;
  });

  const start = useCallback(
    (runId?: string) => {
      if (busy.current) return;
      busy.current = true;
      controller.current?.abort();
      const next = new AbortController();
      controller.current = next;
      setState(initialPipelineState());
      setRunning(true);
      const run = hill.isLive
        ? runLiveAnalysis(hill.slug, setState, next.signal, { runId, trails: hill.trails })
        : runPipeline(hill, setState, next.signal);
      run.finally(() => {
        if (next.signal.aborted) return;
        busy.current = false;
        setRunning(false);
        if (hill.isLive) {
          onLiveRunDone.current?.();
        }
      });
    },
    [hill],
  );

  const analyze = useCallback(() => start(), [start]);

  // A page opened while a run was going follows that run, once.
  const followed = useRef(false);
  const activeRunId = options.activeRunId ?? null;
  useEffect(() => {
    if (followed.current || !activeRunId || !hill.isLive) return;
    followed.current = true;
    start(activeRunId);
  }, [activeRunId, hill.isLive, start]);

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
