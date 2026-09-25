import { isAgentEvent, isRunUpdate } from "./agent-events";
import { getRun, runStreamUrl } from "./api";
import type { AgentEvent, Run } from "./types";

export interface RunHandlers {
  /** A snapshot or phase update. The run's final update has a status other than "running". */
  onRun: (run: Run) => void;
  /** An agent started, finished, or failed. */
  onEvent: (event: AgentEvent) => void;
  /** The stream ended before the run did, and the run could not be found again. */
  onLost: () => void;
}

const MAX_RECONNECTS = 2;
const RECONNECT_MS = 1000;

/**
 * Follow a run on WS /runs/{run_id}/stream until its final RunUpdate. When the socket drops
 * mid-run, ask GET /runs/{run_id}: a finished run reports its result, a running one gets up to
 * two reconnects, and anything else counts as a lost stream. Returns a function that stops.
 */
export function followRun(runId: string, handlers: RunHandlers): () => void {
  let socket: WebSocket | null = null;
  let finished = false;
  let stopped = false;
  let reconnects = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const recover = async () => {
    try {
      const run = await getRun(runId);
      if (stopped) {
        return;
      }
      if (run && run.status !== "running") {
        finished = true;
        handlers.onRun(run);
        return;
      }
      if (run && reconnects < MAX_RECONNECTS) {
        reconnects += 1;
        timer = setTimeout(connect, RECONNECT_MS * reconnects);
        return;
      }
    } catch {
      // The API is unreachable: the stream is lost.
    }
    if (!stopped) {
      handlers.onLost();
    }
  };

  function connect() {
    socket = new WebSocket(runStreamUrl(runId));
    socket.onmessage = (message: MessageEvent<string>) => {
      let data: unknown;
      try {
        data = JSON.parse(message.data);
      } catch {
        return;
      }
      if (isRunUpdate(data)) {
        if (data.run.status !== "running") {
          finished = true;
        }
        handlers.onRun(data.run);
      } else if (isAgentEvent(data)) {
        handlers.onEvent(data);
      }
    };
    socket.onclose = () => {
      if (!finished && !stopped) {
        void recover();
      }
    };
  }

  connect();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}
