import { followRun } from "@/lib/run-stream";
import { startAnalysis } from "@/lib/api";
import { initialPipelineState } from "@/lib/pipeline/orchestrator";
import {
  PIPELINE_AGENTS,
  type PipelineAgentId,
  type PipelineAgentState,
  type PipelineState,
  type ReactiveMeasure,
  type TrailRisk,
} from "@/lib/hill";
import type { Advisory, AgentEvent, AgentName, Run } from "@/lib/types";

/**
 * The hill card shows five rows. The API runs seven agents. Trail, history, and routes
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

interface Outcome {
  orchestrator: PipelineState["orchestrator"];
  error: string | null;
  measures: ReactiveMeasure[] | null;
  advisory: Advisory | null;
}

function project(
  events: Partial<Record<AgentName, AgentEvent>>,
  outcome: Outcome,
  firstSeen: Partial<Record<PipelineAgentId, number>>,
): PipelineState {
  const agents = {} as PipelineState["agents"];
  for (const id of PIPELINE_AGENTS) {
    const group = CARD_AGENTS[id].map((name) => events[name]).filter((event): event is AgentEvent => event != null);
    if (group.length === 0) {
      agents[id] = idleAgent(id);
      continue;
    }
    const failed = group.find((event) => event.status === "error");
    const running = group.some((event) => event.status === "running");
    const waiting = CARD_AGENTS[id].some((name) => events[name] == null);
    const status = failed ? "error" : running || waiting ? "running" : "done";
    const latest = failed ?? [...group].reverse().find((event) => event.status === "running") ?? group[group.length - 1]!;
    const started = group.map((event) => (event.trace?.started_at ? Date.parse(event.trace.started_at) : NaN)).filter((t) => !Number.isNaN(t));
    const finished = group.map((event) => (event.trace?.finished_at ? Date.parse(event.trace.finished_at) : NaN)).filter((t) => !Number.isNaN(t));
    // Without trace timestamps, the first time this card was seen stands in, so the elapsed
    // time does not restart on every repaint.
    const seen = (firstSeen[id] ??= Date.now());
    agents[id] = {
      id,
      status,
      summary: latest.summary,
      trace: group.flatMap(traceLines),
      startedAt: started.length ? Math.min(...started) : seen,
      finishedAt: status === "done" || status === "error" ? (finished.length ? Math.max(...finished) : Date.now()) : null,
    };
  }
  return { ...outcome, agents };
}

function normalizedName(name: string): string {
  return name.toLowerCase().replace(/^the\s+/, "").replace(/\s+trail$/, "").trim();
}

function measuresFromAdvisory(advisory: Advisory, trails: readonly TrailRisk[]): ReactiveMeasure[] {
  const timing = advisory.response.priority_rank >= 2 ? "within-1h" : "within-6h";
  // A route that is also one of the card's lettered trails carries its badge.
  const letters = new Map(trails.map((trail) => [normalizedName(trail.name), trail.letter]));
  const measures: ReactiveMeasure[] = advisory.avoid.map((route) => ({
    category: "closures" as const,
    title: `Keep hikers off ${route.trail}`,
    detail: `${route.reason} ${route.guidance}`.trim(),
    timing: "now" as const,
    letter: letters.get(normalizedName(route.trail)) ?? null,
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
  if (advisory.safe.length > 0) {
    measures.push({
      category: "public",
      title: `Send hikers to ${advisory.safe.map((route) => route.trail).join(", ")}`,
      detail: advisory.safe.map((route) => `${route.trail}: ${route.guidance}`).join(" "),
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
  if (advisory.response.escalate_if) {
    measures.push({
      category: "monitoring",
      title: "Escalate if conditions change",
      detail: advisory.response.escalate_if,
      timing: "within-24h",
      letter: null,
    });
  }
  return measures;
}

export interface LiveRunOptions {
  /** A run already going, such as the one a page opened mid-run: follow it instead of starting one. */
  runId?: string;
  /** The card's lettered trails, so a measure about one of them carries its badge. */
  trails?: readonly TrailRisk[];
}

/**
 * Starts POST /mountains/{slug}/analyze and paints the hill-card pipeline from the live
 * WebSocket. The API calls Gemini or xAI with the keys in the repo root .env.
 */
export function runLiveAnalysis(
  slug: string,
  onUpdate: (state: PipelineState) => void,
  signal: AbortSignal,
  options: LiveRunOptions = {},
): Promise<void> {
  const events: Partial<Record<AgentName, AgentEvent>> = {};
  const firstSeen: Partial<Record<PipelineAgentId, number>> = {};
  let stop = () => {};

  const publish = (
    orchestrator: PipelineState["orchestrator"],
    error: string | null,
    measures: ReactiveMeasure[] | null = null,
    advisory: Advisory | null = null,
  ) => {
    if (signal.aborted) {
      return;
    }
    onUpdate(project(events, { orchestrator, error, measures, advisory }, firstSeen));
  };

  return new Promise((resolve) => {
    const finish = () => {
      stop();
      resolve();
    };
    signal.addEventListener("abort", finish, { once: true });

    onUpdate({ ...initialPipelineState(), orchestrator: "running" });

    (options.runId ? Promise.resolve(options.runId) : startAnalysis(slug, { signal }))
      .then((runId) => {
        if (signal.aborted) {
          finish();
          return;
        }
        stop = followRun(runId, {
          onEvent(event) {
            events[event.agent] = event;
            publish("running", null);
          },
          onRun(run: Run) {
            for (const event of Object.values(run.agents)) {
              if (event) {
                events[event.agent] = event;
              }
            }
            if (run.status === "running") {
              publish("running", null);
              return;
            }
            if (run.status === "error") {
              publish("error", run.error ? `${run.message} ${run.error}` : run.message);
              finish();
              return;
            }
            const advisory = run.advisory ?? null;
            publish("done", null, advisory ? measuresFromAdvisory(advisory, options.trails ?? []) : null, advisory);
            finish();
          },
          onLost() {
            publish("error", "Lost the analysis stream. The API may still be running the agents.");
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
