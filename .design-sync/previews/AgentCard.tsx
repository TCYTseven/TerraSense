import { AgentCard, type PipelineAgentState } from "terrasense-ui";

// AgentCard: one agent's name, status, and one-line summary. A click opens its full reasoning
// trace directly beneath it (the parent keeps one open at a time). The running card pulses.

const T0 = 1_727_300_000_000;

const TERRAIN_TRACE = [
  "Loaded the 10 m elevation grid for Mount Rainier (660 km² box, peak 4392 m).",
  "Sampled slope under 5 trail regions: Kautz Creek Trail 34°, Van Trump Trail 36°, Comet Falls 31°, Glacier Basin Trail 29°, Skyline Trail 27°.",
  "Mean hillside slope across the box is 24°; 3 of 5 regions sit at 30° or steeper.",
  "Steepest region: Van Trump Trail at 36°, inside the 30–40° band where shallow slides start most often.",
];

const card = (agent: PipelineAgentState, expanded = false, notReached = false) => (
  <div className="w-[560px] bg-card p-4">
    <AgentCard agent={agent} expanded={expanded} notReached={notReached} onToggle={() => {}} />
  </div>
);

/** Done, collapsed: name, time, status word, and the one-line summary. */
export const Done = () =>
  card({
    id: "terrain",
    status: "done",
    summary: "3 of 5 regions at 30°+, steepest Van Trump Trail 36°",
    trace: TERRAIN_TRACE,
    startedAt: T0,
    finishedAt: T0 + 2400,
  });

/** Done, expanded: the numbered trace sits directly beneath the card. */
export const DoneExpanded = () =>
  card(
    {
      id: "terrain",
      status: "done",
      summary: "3 of 5 regions at 30°+, steepest Van Trump Trail 36°",
      trace: TERRAIN_TRACE,
      startedAt: T0,
      finishedAt: T0 + 2400,
    },
    true,
  );

/** Running and expanded: the card pulses and the trace grows, ending in "Thinking…". */
export const RunningExpanded = () =>
  card(
    {
      id: "weather",
      status: "running",
      summary: "Reading the rain record",
      trace: [
        "Pulled the 72-hour record and forecast for the Mount Rainier box.",
        "Past 72 h: 2.3 in of rain at Paradise, 1.6 in at Longmire. Soils near saturation below 1,800 m.",
      ],
      startedAt: T0,
      finishedAt: null,
    },
    true,
  );

/** Idle before a run. */
export const Idle = () =>
  card({ id: "synthesizer", status: "idle", summary: "", trace: [], startedAt: null, finishedAt: null });

/** Failed: the status word reads "failed" and the error sits under the trace. */
export const Failed = () =>
  card(
    {
      id: "weather",
      status: "error",
      summary: "Weather could not reach its data source.",
      trace: ["Pulled the 72-hour record and forecast for the Mount Rainier box."],
      startedAt: T0,
      finishedAt: T0 + 900,
    },
    true,
  );
