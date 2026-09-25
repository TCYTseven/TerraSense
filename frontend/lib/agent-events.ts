import { AGENT_NAMES, AGENT_STATUSES, type AgentEvent } from "./types";

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
    !Array.isArray(event.payload)
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
