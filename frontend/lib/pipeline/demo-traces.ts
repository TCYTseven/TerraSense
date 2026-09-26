/**
 * Scripted agent traces for the hill card, built from the HillView so every step names real
 * trails, scores, and slopes. Illustrative until the backend's run stream replaces the scripted
 * runner; nothing here is model output.
 */

import type { HillView, PipelineAgentId, ReactiveMeasure, TrailRisk } from "../hill";

export interface ScriptedAgent {
  /** The steps, in order. The runner emits one at a time. */
  steps: string[];
  /** The card's one-line summary once the agent finishes. */
  summary: string;
  /** Total time the agent takes, in ms. Spread evenly across the steps. */
  durationMs: number;
}

const LEVEL_WORDS = { low: "Low", moderate: "Moderate", high: "High", extreme: "Extreme" } as const;

function pct(score: number): string {
  return score.toFixed(2);
}

function trailList(trails: TrailRisk[], describe: (t: TrailRisk) => string): string {
  return trails.map(describe).join(", ");
}

function terrain(hill: HillView): ScriptedAgent {
  const { trails, stats } = hill;
  if (trails.length === 0) {
    return {
      steps: [`Loaded the elevation grid for ${hill.name}.`, "No trail regions are scored for this mountain yet."],
      summary: "No trail regions to sample",
      durationMs: 1600,
    };
  }
  const steepest = [...trails].sort((a, b) => b.slopeDeg - a.slopeDeg)[0];
  const over30 = trails.filter((t) => t.slopeDeg >= 30);
  return {
    steps: [
      `Loaded the 10 m elevation grid for ${hill.name} (${stats.areaKm2} km² box, peak ${stats.elevationM} m).`,
      `Sampled slope under ${trails.length} trail regions: ${trailList(trails, (t) => `${t.name} ${t.slopeDeg}°`)}.`,
      `Mean hillside slope across the box is ${stats.meanSlopeDeg}°; ${over30.length} of ${trails.length} regions sit at 30° or steeper.`,
      `Steepest region: ${steepest.name} at ${steepest.slopeDeg}°, inside the 30–40° band where shallow slides start most often.`,
      `Primary driver per region: ${trailList(trails, (t) => `${t.letter} ${t.primaryFactor.toLowerCase()}`)}.`,
    ],
    summary: `${over30.length} of ${trails.length} regions at 30°+, steepest ${steepest.name} ${steepest.slopeDeg}°`,
    durationMs: 2400,
  };
}

function weather(hill: HillView): ScriptedAgent {
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

function trailsAgent(hill: HillView): ScriptedAgent {
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
        (t) => `${t.letter}. ${t.name}: ${pct(t.score)} ${LEVEL_WORDS[t.level].toLowerCase()}, driven by ${t.primaryFactor.toLowerCase()}.`,
      ),
      `${atRisk.length} of ${trails.length} trails are high or extreme; ${top.name} leads at ${pct(top.score)}.`,
    ],
    summary: `Ranked A–${trails[trails.length - 1].letter}; ${top.name} leads at ${pct(top.score)}`,
    durationMs: 2800,
  };
}

function synthesizer(hill: HillView): ScriptedAgent {
  const { trails, risk } = hill;
  const top = trails[0];
  return {
    steps: [
      "Read the Terrain, Weather, and Trails reports.",
      top
        ? `Weighted the trail scores by exposure; ${top.name} (${pct(top.score)}) and its ${top.primaryFactor.toLowerCase()} carry the most weight.`
        : "No trail scores to weight; used the mountain's current level.",
      "Raised confidence: the rain story and the steep-slope regions point the same way.",
      `Overall score ${pct(risk.score)}, level ${LEVEL_WORDS[risk.level]}.`,
    ],
    summary: `Overall ${LEVEL_WORDS[risk.level]} at ${pct(risk.score)}`,
    durationMs: 1600,
  };
}

function alertWriter(hill: HillView): ScriptedAgent {
  const measures = demoMeasures(hill);
  const rangers = measures.filter((m) => m.audience === "rangers").length;
  const publicDrafts = measures.length - rangers;
  return {
    steps: [
      `Read the final assessment: ${LEVEL_WORDS[hill.risk.level]} at ${pct(hill.risk.score)}.`,
      ...measures.map((m) => `${m.audience === "rangers" ? "Ranger action" : "Public draft"}: ${m.title}.`),
      "Held every public notice as a draft. Nothing is sent until a ranger approves it.",
    ],
    summary: `${rangers} ranger action${rangers === 1 ? "" : "s"}, ${publicDrafts} public draft${publicDrafts === 1 ? "" : "s"}`,
    durationMs: 1500,
  };
}

const SCRIPTS: Record<PipelineAgentId, (hill: HillView) => ScriptedAgent> = {
  terrain,
  weather,
  trails: trailsAgent,
  synthesizer,
  alertWriter,
};

export function scriptFor(id: PipelineAgentId, hill: HillView): ScriptedAgent {
  return SCRIPTS[id](hill);
}

/** Three to five measures: ranger actions first, then public notices, which are drafts. */
export function demoMeasures(hill: HillView): ReactiveMeasure[] {
  const [a, b, c] = hill.trails;
  if (!a) {
    return [
      {
        audience: "rangers",
        title: "Review conditions before the next storm",
        detail: `No trails are scored for ${hill.name} yet. Check drainages by hand.`,
        letter: null,
      },
      {
        audience: "public",
        title: "General slide advisory",
        detail: `Heavy rain raises slide risk on ${hill.name}. Stay off steep ground near creeks.`,
        letter: null,
      },
    ];
  }
  const measures: ReactiveMeasure[] = [
    {
      audience: "rangers",
      title: `Close ${a.name}`,
      detail: `${pct(a.score)} ${a.level}, ${a.slopeDeg}° with ${a.primaryFactor.toLowerCase()}. Close it through the storm and post the trailhead.`,
      letter: a.letter,
    },
  ];
  if (b) {
    measures.push({
      audience: "rangers",
      title: `Send a patrol to ${b.name}`,
      detail: `Walk the crossings at ${b.slopeDeg}° and report fresh cracks or muddy runoff before 18:00.`,
      letter: b.letter,
    });
  }
  measures.push({
    audience: "public",
    title: `${a.name} closed`,
    detail: `${a.name} is closed for slide risk during heavy rain. Choose another route and stay out of creek channels.`,
    letter: a.letter,
  });
  if (c) {
    measures.push({
      audience: "public",
      title: `Caution on ${c.name}`,
      detail: `Rain on steep ground raises slide risk on ${c.name}. Turn back if you hear rumbling or see muddy water.`,
      letter: c.letter,
    });
  }
  return measures;
}
