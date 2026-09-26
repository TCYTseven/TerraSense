import { AGENT_NAMES, AGENT_STATUSES, type AgentEvent, PROVIDER_NAMES, RUN_STATUSES, type RunUpdate } from "./types";

/**
 * True when a value has the AgentEvent shape. Use it on anything parsed from
 * JSON, such as fixtures and stream messages, because JSON widens the
 * agent and status literals to plain strings.
 */
export function isAgentEvent(value: unknown): value is AgentEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const event = value as Record<string, unknown>;
  return (
    typeof event.run_id === "string" &&
    (AGENT_NAMES as readonly unknown[]).includes(event.agent) &&
    (AGENT_STATUSES as readonly unknown[]).includes(event.status) &&
    typeof event.summary === "string" &&
    typeof event.payload === "object" &&
    event.payload !== null &&
    !Array.isArray(event.payload) &&
    (event.trace === undefined || event.trace === null || isTrace(event.trace))
  );
}

/** The parts of an AgentTrace the reasoning panel reads without checking again. */
function isTrace(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const trace = value as Record<string, unknown>;
  const route = trace.route as Record<string, unknown> | undefined;
  return (
    typeof route === "object" &&
    route !== null &&
    (PROVIDER_NAMES as readonly unknown[]).includes(route.provider) &&
    typeof route.label === "string" &&
    typeof route.reason === "string" &&
    Array.isArray(route.rules) &&
    Array.isArray(trace.tools) &&
    Array.isArray(trace.attempts) &&
    Array.isArray(trace.thoughts) &&
    Array.isArray(trace.reasoning) &&
    Array.isArray(trace.checks)
  );
}

/** Returns the value as AgentEvent[], or throws naming the first entry that does not fit. */
export function parseAgentEvents(value: unknown): AgentEvent[] {
  if (!Array.isArray(value)) {
    throw new TypeError("Expected an array of agent events");
  }
  const badIndex = value.findIndex((item) => !isAgentEvent(item));
  if (badIndex !== -1) {
    throw new TypeError(`Agent event ${badIndex} does not match AgentEvent`);
  }
  return value as AgentEvent[];
}

/** True when a stream message is a RunUpdate: the run's snapshot or a phase change. */
export function isRunUpdate(value: unknown): value is RunUpdate {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const message = value as Record<string, unknown>;
  const run = message.run as Record<string, unknown> | undefined;
  return (
    message.kind === "run" &&
    typeof run === "object" &&
    run !== null &&
    typeof run.id === "string" &&
    (RUN_STATUSES as readonly unknown[]).includes(run.status) &&
    typeof run.message === "string" &&
    typeof run.agents === "object" &&
    run.agents !== null &&
    Object.values(run.agents).every(isAgentEvent)
  );
}
