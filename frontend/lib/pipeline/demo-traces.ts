/**
 * Scripted agent traces for the mountain page, built from the MountainView so every step names real
 * trails, scores, and slopes. Illustrative until the backend's run stream replaces the scripted
 * runner; nothing here is model output.
 */

import { MEASURE_TIMING_LABELS, MEASURE_TIMINGS, type MountainView, type PipelineAgentId, type ReactiveMeasure, type TrailRisk } from "../mountain-view";

export interface ScriptedAgent {
  /** The steps, in order. The runner emits one at a time. */
  steps: string[];
  /** The card's one-line summary once the agent finishes. */
  summary: string;
  /** Total time the agent takes, in ms. Spread evenly across the steps. */
  durationMs: number;
}

const LEVEL_WORDS = { low: "Low", moderate: "Moderate", high: "High", extreme: "Extreme" } as const;

function pct(score: number | null): string {
  return score === null ? "unscored" : score.toFixed(2);
}

function slope(t: TrailRisk): string {
  return t.slopeDeg === null ? "unmeasured slope" : `${t.slopeDeg}°`;
}

function factor(t: TrailRisk): string {
  return (t.primaryFactor ?? "terrain").toLowerCase();
}

function trailList(trails: TrailRisk[], describe: (t: TrailRisk) => string): string {
  return trails.map(describe).join(", ");
}

function terrain(hill: MountainView): ScriptedAgent {
  const { trails, stats } = hill;
  if (trails.length === 0) {
    return {
      steps: [`Loaded the elevation grid for ${hill.name}.`, "No trail regions are scored for this mountain yet."],
      summary: "No trail regions to sample",
      durationMs: 1600,
    };
  }
  const steepest = [...trails].sort((a, b) => (b.slopeDeg ?? 0) - (a.slopeDeg ?? 0))[0];
  const over30 = trails.filter((t) => (t.slopeDeg ?? 0) >= 30);
  return {
    steps: [
      `Loaded the 10 m elevation grid for ${hill.name} (${stats.areaKm2} km² box, peak ${stats.elevationM} m).`,
      `Sampled slope under ${trails.length} trail regions: ${trailList(trails, (t) => `${t.name} ${slope(t)}`)}.`,
      `Mean hillside slope across the box is ${stats.meanSlopeDeg}°; ${over30.length} of ${trails.length} regions sit at 30° or steeper.`,
      `Steepest region: ${steepest.name} at ${slope(steepest)}, inside the 30–40° band where shallow slides start most often.`,
      `Primary driver per region: ${trailList(trails, (t) => `${t.letter} ${factor(t)}`)}.`,
    ],
    summary: `${over30.length} of ${trails.length} regions at 30°+, steepest ${steepest.name} ${slope(steepest)}`,
    durationMs: 2400,
  };
}

function weather(hill: MountainView): ScriptedAgent {
  return {
    steps: [
      `Pulled the 72-hour record and forecast for the ${hill.name} box.`,
      "Past 72 h: 2.3 in of rain at Paradise, 1.6 in at Longmire. Soils near saturation below 1,800 m.",
      "Next 24 h: an atmospheric river brings 1.4 in more, peaking at 0.3 in/h after 02:00.",
      "Freezing level rises to 2,900 m, so rain falls on snow across the lower glaciers.",
      "Rain on saturated ground plus snowmelt pushes runoff above the 1 in / 24 h trigger.",
    ],
    summary: "2.3 in in 72 h, 1.4 in more in 24 h, rain on snow",
    durationMs: 1800,
  };
}

function trailsAgent(hill: MountainView): ScriptedAgent {
  const { trails } = hill;
  if (trails.length === 0) {
    return {
      steps: ["Read the trail list.", "No trails are scored for this mountain yet."],
      summary: "No trails scored",
      durationMs: 1500,
    };
  }
  const top = trails[0];
  const atRisk = trails.filter((t) => t.level === "high" || t.level === "extreme");
  return {
    steps: [
      `Read ${trails.length} trails that cross the scored regions.`,
      ...trails.map(
        (t) => `${t.letter}. ${t.name}: ${pct(t.score)} ${LEVEL_WORDS[t.level].toLowerCase()}, driven by ${factor(t)}.`,
      ),
      `${atRisk.length} of ${trails.length} trails are high or extreme; ${top.name} leads at ${pct(top.score)}.`,
    ],
    summary: `Ranked A–${trails[trails.length - 1].letter}; ${top.name} leads at ${pct(top.score)}`,
    durationMs: 2800,
  };
}

function synthesizer(hill: MountainView): ScriptedAgent {
  const { trails, risk } = hill;
  const top = trails[0];
  return {
    steps: [
      "Read the Terrain, Weather, and Trails reports.",
      top
        ? `Weighted the trail scores by exposure; ${top.name} (${pct(top.score)}) and its ${factor(top)} carry the most weight.`
        : "No trail scores to weight; used the mountain's current level.",
      "Raised confidence: the rain story and the steep-slope regions point the same way.",
      `Overall score ${pct(risk.score)}, level ${LEVEL_WORDS[risk.level]}.`,
    ],
    summary: `Overall ${LEVEL_WORDS[risk.level]} at ${pct(risk.score)}`,
    durationMs: 1600,
  };
}

function alertWriter(hill: MountainView): ScriptedAgent {
  const measures = demoMeasures(hill);
  const drafts = measures.filter((m) => m.category === "public").length;
  const actions = measures.length - drafts;
  return {
    steps: [
      `Read the final assessment: ${LEVEL_WORDS[hill.risk.level]} at ${pct(hill.risk.score)}.`,
      ...MEASURE_TIMINGS.map((timing) => {
        const titles = measures.filter((m) => m.timing === timing).map((m) => m.title);
        return titles.length ? `${MEASURE_TIMING_LABELS[timing]}: ${titles.join("; ")}.` : null;
      }).filter((step): step is string => step !== null),
      "Held every public notice as a draft. Nothing is sent until a ranger approves it.",
    ],
    summary: `${actions} response action${actions === 1 ? "" : "s"}, ${drafts} public draft${drafts === 1 ? "" : "s"}`,
    durationMs: 1500,
  };
}

const SCRIPTS: Record<PipelineAgentId, (hill: MountainView) => ScriptedAgent> = {
  terrain,
  weather,
  trails: trailsAgent,
  synthesizer,
  alertWriter,
};

export function scriptFor(id: PipelineAgentId, hill: MountainView): ScriptedAgent {
  return SCRIPTS[id](hill);
}

/** Three to five measures: ranger actions first, then public notices, which are drafts. */
export function demoMeasures(hill: MountainView): ReactiveMeasure[] {
  const [a, b, c] = hill.trails;
  if (!a) {
    return [
      {
        category: "monitoring",
        title: "Check drainages by hand before the next storm",
        detail: `No trails are scored for ${hill.name} yet, so nothing points to one slope.`,
        timing: "within-24h",
        letter: null,
      },
      {
        category: "public",
        title: "General slide advisory",
        detail: `Heavy rain raises slide risk on ${hill.name}. Stay off steep ground near creeks.`,
        timing: "within-6h",
        letter: null,
      },
    ];
  }
  const severe = hill.trails.filter((t) => t.level === "extreme" || t.level === "high");
  const measures: ReactiveMeasure[] = [
    {
      category: "closures",
      title: `Close ${a.name}`,
      detail: `${pct(a.score)} ${a.level}, ${slope(a)} with ${factor(a)}. Gate the trailhead and post closure signs through the storm.`,
      timing: "now",
      letter: a.letter,
    },
  ];
  if (b) {
    measures.push({
      category: "closures",
      title: `Restrict ${b.name} to the lower miles`,
      detail: `Hold hikers below the ${slope(b)} crossings until a patrol clears them.`,
      timing: "within-1h",
      letter: b.letter,
    });
  }
  measures.push({
    category: "evacuation",
    title: `Sweep the ${severe.length > 1 ? `${severe.length} flagged drainages` : "flagged drainage"}`,
    detail: `Clear backcountry camps and day hikers from ${trailList(severe.slice(0, 3), (t) => t.name)}. Turn people back at the trailheads.`,
    timing: "now",
    letter: null,
  });
  measures.push({
    category: "evacuation",
    title: "Open a shelter point at the nearest visitor center",
    detail: "Somewhere dry for swept hikers to check in, so rangers can account for everyone on the permit list.",
    timing: "within-6h",
    letter: null,
  });
  measures.push({
    category: "rescue",
    title: "Pre-stage a search and rescue team",
    detail: `Stage a team and litter at the ${a.name} trailhead, and confirm a helicopter can fly if the ceiling allows.`,
    timing: "within-6h",
    letter: a.letter,
  });
  if (b) {
    measures.push({
      category: "monitoring",
      title: `Post a spotter on ${b.name}`,
      detail: `Watch the crossings for fresh cracks, muddy runoff, or a sudden drop in creek flow, which can come before a debris flow. Report by radio every 30 min.`,
      timing: "within-1h",
      letter: b.letter,
    });
  }
  if (c) {
    measures.push({
      category: "monitoring",
      title: `Patrol ${c.name} after the heaviest rain`,
      detail: `Walk it at first light and log any new slumps or downed trees at ${slope(c)}.`,
      timing: "within-24h",
      letter: c.letter,
    });
  }
  measures.push({
    category: "coordination",
    title: "Brief county emergency management",
    detail: `Share the flagged trails and the ${pct(hill.risk.score)} ${hill.risk.level} level, and agree who closes the roads below the drainages.`,
    timing: "within-1h",
    letter: null,
  });
  measures.push({
    category: "coordination",
    title: "Ask the weather service for rain updates",
    detail: "Request a call if the next 24 h totals rise, and re-run Analyze now when they do.",
    timing: "within-6h",
    letter: null,
  });
  measures.push({
    category: "public",
    title: `${a.name} closed`,
    detail: `${a.name} is closed for slide risk during heavy rain. Choose another route and stay out of creek channels.`,
    timing: "now",
    letter: a.letter,
  });
  if (c) {
    measures.push({
      category: "public",
      title: `Caution on ${c.name}`,
      detail: `Rain on steep ground raises slide risk on ${c.name}. Turn back if you hear rumbling or see muddy water.`,
      timing: "within-1h",
      letter: c.letter,
    });
  }
  return measures;
}
