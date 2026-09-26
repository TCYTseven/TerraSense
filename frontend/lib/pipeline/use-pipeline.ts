"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { HillView, PipelineState } from "../hill";
import { initialPipelineState, runPipeline } from "./orchestrator";

export interface PipelineControls {
  state: PipelineState;
  /** True from the click until the orchestrator finishes or fails. */
  running: boolean;
  /** Starts a run. Does nothing while one is running. */
  analyze: () => void;
}

/**
 * Holds the pipeline's state and runs it on demand. The run is scripted today; swapping the
 * source passed to `runPipeline` for a run-stream adapter changes nothing here or in the UI.
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
    runPipeline(hill, setState, next.signal).finally(() => {
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
