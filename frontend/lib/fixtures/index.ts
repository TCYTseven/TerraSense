import { parseAgentEvents } from "../agent-events";
import type { AgentEvent } from "../types";
import runJson from "./run.json";

/**
 * One finished five-agent run, in stream order, for building the agent panel
 * before the LLM pipeline exists. The values are illustrative, not model output.
 * Parsing throws on import if run.json drifts from AgentEvent.
 */
export const FIXTURE_RUN: AgentEvent[] = parseAgentEvents(runJson);
