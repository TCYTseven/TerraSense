import { parseAgentEvents } from "../agent-events";
import type { AgentEvent } from "../types";
import runJson from "./run.json";

/**
 * One finished run, in stream order: the five analysts start together and answer before the
 * Risk Synthesizer and the Alert Writer run. For building the agent panel without the backend.
 * The values are illustrative, not model output.
 * Parsing throws on import if run.json drifts from AgentEvent.
 */
export const FIXTURE_RUN: AgentEvent[] = parseAgentEvents(runJson);
