import { AgentPipeline, initialPipelineState, type PipelineAgentState, type PipelineState } from "terrasense-ui";

// AgentPipeline: the Orchestrator node wired to five agent cards. Terrain, Weather, and Trails
// run in parallel, then the Synthesizer, then the Mass Alert Writer. A card click opens its
// trace beneath it, one at a time. To play a scripted run in a design, use usePipeline(hill).

const T0 = 1_727_300_000_000;

const agent = (
  id: PipelineAgentState["id"],
  status: PipelineAgentState["status"],
  summary: string,
  start: number | null,
  end: number | null,
): PipelineAgentState => ({
  id,
  status,
  summary,
  trace: status === "idle" ? [] : [summary],
  startedAt: start === null ? null : T0 + start,
  finishedAt: end === null ? null : T0 + end,
});

/** Before the first run: one muted line. */
export const BeforeFirstRun = () => (
  <div className="w-[600px] bg-card px-5 py-4">
    <AgentPipeline state={initialPipelineState()} />
  </div>
);

const RUNNING: PipelineState = {
  orchestrator: "running",
  agents: {
    terrain: agent("terrain", "done", "3 of 5 regions at 30°+, steepest Van Trump Trail 36°", 0, 2400),
    weather: agent("weather", "done", "2.3 in in 72 h, 1.4 in more in 24 h, rain on snow", 0, 1800),
    trails: agent("trails", "running", "Ranking the five trails", 0, null),
    synthesizer: agent("synthesizer", "idle", "", null, null),
    alertWriter: agent("alertWriter", "idle", "", null, null),
  },
  measures: null,
  error: null,
};

/** Mid-run: two parallel agents done, Trails still running, the rest waiting. */
export const MidRun = () => (
  <div className="w-[600px] bg-card px-5 py-4">
    <AgentPipeline state={RUNNING} />
  </div>
);

/** Finished: every card done, and the Orchestrator reports the total time. */
export const Finished = () => (
  <div className="w-[600px] bg-card px-5 py-4">
    <AgentPipeline
      state={{
        orchestrator: "done",
        agents: {
          terrain: agent("terrain", "done", "3 of 5 regions at 30°+, steepest Van Trump Trail 36°", 0, 2400),
          weather: agent("weather", "done", "2.3 in in 72 h, 1.4 in more in 24 h, rain on snow", 0, 1800),
          trails: agent("trails", "done", "Ranked A–E; Kautz Creek Trail leads at 0.74", 0, 2800),
          synthesizer: agent("synthesizer", "done", "Overall High at 0.52", 2800, 4400),
          alertWriter: agent("alertWriter", "done", "7 response actions, 2 public drafts", 4400, 5900),
        },
        measures: [],
        error: null,
      }}
    />
  </div>
);

/** Failed at Weather: the Orchestrator says so and the later cards read "not reached". */
export const FailedRun = () => (
  <div className="w-[600px] bg-card px-5 py-4">
    <AgentPipeline
      state={{
        orchestrator: "error",
        agents: {
          terrain: agent("terrain", "done", "3 of 5 regions at 30°+, steepest Van Trump Trail 36°", 0, 2400),
          weather: agent("weather", "error", "Weather could not reach its data source.", 0, 900),
          trails: agent("trails", "done", "Ranked A–E; Kautz Creek Trail leads at 0.74", 0, 2800),
          synthesizer: agent("synthesizer", "idle", "", null, null),
          alertWriter: agent("alertWriter", "idle", "", null, null),
        },
        measures: null,
        error: "The run failed at Weather: it could not reach its data source.",
      }}
    />
  </div>
);
