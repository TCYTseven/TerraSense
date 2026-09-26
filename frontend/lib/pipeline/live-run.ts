import { followRun } from "@/lib/run-stream";
import { startAnalysis } from "@/lib/api";
import { initialPipelineState } from "@/lib/pipeline/orchestrator";
import {
  PIPELINE_AGENTS,
  type PipelineAgentId,
  type PipelineAgentState,
  type PipelineState,
  type ReactiveMeasure,
} from "@/lib/mountain-view";
import { ANALYST_NAMES, type Advisory, type AgentEvent, type AgentName, type Run } from "@/lib/types";

/**
 * The mountain page shows five rows. The API runs seven agents. Trail, history, and routes
 * share the Trails row so every real model call still appears in the trace.
 */
const CARD_AGENTS: Record<PipelineAgentId, readonly AgentName[]> = {
  terrain: ["terrain"],
  weather: ["weather"],
  trails: ["trail", "history", "routes"],
  synthesizer: ["synthesizer"],
  alertWriter: ["writer"],
};

const AGENT_LABEL: Record<AgentName, string> = {
  terrain: "Terrain",
  weather: "Weather",
  trail: "Trails",
  history: "History",
  routes: "Routes",
  synthesizer: "Synthesizer",
  writer: "Alert writer",
};

function idleAgent(id: PipelineAgentId): PipelineAgentState {
  return { id, status: "idle", summary: "", trace: [], startedAt: null, finishedAt: null };
}

function withoutModelNames(text: string): string {
  return text
    .replace(/\b(?:grok|gemini)[- .][\w.]+(?:[- ]flash)?\b/gi, "")
    .replace(/\bGrok \d+(?:\.\d+)?\b/g, "")
    .replace(/\bGemini [\d.]+ Flash\b/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.])/g, "$1")
    .trim();
}

function traceLines(event: AgentEvent): string[] {
  const lines: string[] = [];
  if (CARD_AGENTS.trails.includes(event.agent)) {
    lines.push(AGENT_LABEL[event.agent]);
  }
  const trace = event.trace;
  if (!trace) {
    return lines;
  }
  const failover = withoutModelNames(trace.route.reason);
  if (failover && /fail|rest|backup|busy|503|unavailable/i.test(trace.route.reason)) {
    lines.push(failover);
  }
  for (const tool of trace.tools) {
    lines.push(`${tool.name}  ${tool.ms} ms`);
  }
  for (const attempt of trace.attempts) {
    if (!attempt.ok) {
      const detail = (attempt.error ?? "request failed").replace(/^HTTP \d+:\s*/, "");
      lines.push(`retry · ${detail}`);
    }
  }
  for (const thought of trace.thoughts) {
    lines.push(thought);
  }
  for (const step of trace.reasoning) {
    lines.push(step);
  }
  for (const check of trace.checks) {
    lines.push(check);
  }
  return lines;
}

function analystsComplete(events: Partial<Record<AgentName, AgentEvent>>): boolean {
  return ANALYST_NAMES.every((name) => {
    const event = events[name];
    return event != null && (event.status === "done" || event.status === "error");
  });
}

/** UI status for one card. The three under "In parallel" move together during the backend fan-out. */
function cardStatus(
  id: PipelineAgentId,
  events: Partial<Record<AgentName, AgentEvent>>,
  orchestrator: PipelineState["orchestrator"],
): PipelineAgentState["status"] {
  const inFanOut = orchestrator === "running" && !analystsComplete(events);

  if (id === "terrain") {
    const event = events.terrain;
    if (event?.status === "error") return "error";
    if (event?.status === "done") return "done";
    if (inFanOut) return "running";
    return "idle";
  }
  if (id === "weather") {
    const event = events.weather;
    if (event?.status === "error") return "error";
    if (event?.status === "done") return "done";
    if (inFanOut) return "running";
    return "idle";
  }
  if (id === "trails") {
    const names = CARD_AGENTS.trails;
    if (names.some((name) => events[name]?.status === "error")) return "error";
    if (names.every((name) => events[name]?.status === "done")) return "done";
    if (inFanOut) return "running";
    return "idle";
  }

  const group = CARD_AGENTS[id].map((name) => events[name]).filter((event): event is AgentEvent => event != null);
  if (group.length === 0) return "idle";
  const failed = group.find((event) => event.status === "error");
  if (failed) return "error";
  const running = group.some((event) => event.status === "running");
  if (running) return "running";
  if (group.every((event) => event.status === "done")) return "done";
  return "idle";
}

function project(events: Partial<Record<AgentName, AgentEvent>>, orchestrator: PipelineState["orchestrator"], error: string | null, measures: ReactiveMeasure[] | null): PipelineState {
  const agents = {} as PipelineState["agents"];
  for (const id of PIPELINE_AGENTS) {
    const names = CARD_AGENTS[id];
    const group = names.map((name) => events[name]).filter((event): event is AgentEvent => event != null);
    const status = cardStatus(id, events, orchestrator);
    if (group.length === 0) {
      agents[id] = {
        ...idleAgent(id),
        status,
        summary: status === "running" ? "Running" : "",
        startedAt: status === "running" ? Date.now() : null,
      };
      continue;
    }
    const failed = group.find((event) => event.status === "error");
    const latest = failed ?? [...group].reverse().find((event) => event.status === "running") ?? group[group.length - 1]!;
    const started = group.map((event) => (event.trace?.started_at ? Date.parse(event.trace.started_at) : NaN)).filter((t) => !Number.isNaN(t));
    const finished = group.map((event) => (event.trace?.finished_at ? Date.parse(event.trace.finished_at) : NaN)).filter((t) => !Number.isNaN(t));
    agents[id] = {
      id,
      status,
      summary: latest.summary,
      trace: group.flatMap(traceLines),
      startedAt: started.length ? Math.min(...started) : status === "running" ? Date.now() : null,
      finishedAt: status === "done" || status === "error" ? (finished.length ? Math.max(...finished) : Date.now()) : null,
    };
  }
  return { orchestrator, agents, measures, error };
}

function measuresFromAdvisory(advisory: Advisory): ReactiveMeasure[] {
  const timing = advisory.response.priority_rank >= 2 ? "within-1h" : "within-6h";
  const measures: ReactiveMeasure[] = advisory.avoid.map((route) => ({
    category: "closures" as const,
    title: `Keep hikers off ${route.trail}`,
    detail: `${route.reason} ${route.guidance}`.trim(),
    timing: "now" as const,
    letter: null,
  }));
  for (const action of advisory.response.actions) {
    measures.push({
      category: "coordination",
      title: action,
      detail: advisory.response.headline,
      timing,
      letter: null,
    });
  }
  measures.push({
    category: "public",
    title: advisory.alert.title,
    detail: advisory.alert.hiker || advisory.alert.body,
    timing,
    letter: null,
  });
  return measures;
}

/**
 * Starts POST /mountains/{slug}/analyze and paints the mountain-page pipeline from the live
 * WebSocket. The API calls Gemini or xAI with the keys in the repo root .env.
 */
export function runLiveAnalysis(
  slug: string,
  onUpdate: (state: PipelineState) => void,
  signal: AbortSignal,
): Promise<void> {
  const events: Partial<Record<AgentName, AgentEvent>> = {};
  let stop = () => {};

  const publish = (orchestrator: PipelineState["orchestrator"], error: string | null, measures: ReactiveMeasure[] | null) => {
    if (signal.aborted) {
      return;
    }
    onUpdate(project(events, orchestrator, error, measures));
  };

  return new Promise((resolve) => {
    const finish = () => {
      stop();
      resolve();
    };
    signal.addEventListener("abort", finish, { once: true });

    onUpdate({ ...initialPipelineState(), orchestrator: "running" });

    startAnalysis(slug, { signal })
      .then((runId) => {
        if (signal.aborted) {
          finish();
          return;
        }
        stop = followRun(runId, {
          onEvent(event) {
            events[event.agent] = event;
            publish("running", null, null);
          },
          onRun(run: Run) {
            for (const event of Object.values(run.agents)) {
              if (event) {
                events[event.agent] = event;
              }
            }
            if (run.status === "running") {
              publish("running", null, null);
              return;
            }
            if (run.status === "error") {
              publish("error", run.error ?? run.message, null);
              finish();
              return;
            }
            publish("done", null, run.advisory ? measuresFromAdvisory(run.advisory) : null);
            finish();
          },
          onLost() {
            publish("error", "Lost the analysis stream. The API may still be running the agents.", null);
            finish();
          },
        });
      })
      .catch((error: unknown) => {
        if (signal.aborted) {
          finish();
          return;
        }
        const message = error instanceof Error ? error.message : String(error);
        onUpdate({ ...initialPipelineState(), orchestrator: "error", error: message });
        finish();
      });
  });
}
