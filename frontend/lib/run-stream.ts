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
// After the reconnects, poll GET /runs/{id} at this pace. A proxy that blocks WebSockets must
// not turn a run that is still going into "lost".
const POLL_MS = 2000;
const MAX_POLL_FAILURES = 5;

/**
 * Follow a run on WS /runs/{run_id}/stream until its final RunUpdate. When the socket drops
 * mid-run, ask GET /runs/{run_id}: a finished run reports its result, a running one gets up to
 * two reconnects and then polling, and a run the API cannot find, or an API that stops
 * answering, counts as a lost stream. Returns a function that stops.
 */
export function followRun(runId: string, handlers: RunHandlers): () => void {
  let socket: WebSocket | null = null;
  let finished = false;
  let stopped = false;
  let reconnects = 0;
  let pollFailures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const poll = async () => {
    try {
      const run = await getRun(runId);
      if (stopped) {
        return;
      }
      if (run === null) {
        handlers.onLost();
        return;
      }
      pollFailures = 0;
      if (run.status !== "running") {
        finished = true;
      }
      handlers.onRun(run);
      if (!finished) {
        timer = setTimeout(() => void poll(), POLL_MS);
      }
      return;
    } catch {
      pollFailures += 1;
    }
    if (stopped) {
      return;
    }
    if (pollFailures >= MAX_POLL_FAILURES) {
      handlers.onLost();
      return;
    }
    timer = setTimeout(() => void poll(), POLL_MS);
  };

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
      if (run) {
        handlers.onRun(run);
        timer = setTimeout(() => void poll(), POLL_MS);
        return;
      }
    } catch {
      // The API is unreachable right now. Polling gives it a few more tries.
      if (!stopped) {
        pollFailures += 1;
        timer = setTimeout(() => void poll(), POLL_MS);
      }
      return;
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
