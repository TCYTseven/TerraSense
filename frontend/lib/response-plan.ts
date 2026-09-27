import type { PipelineAgentState, ReactiveMeasure } from "@/lib/mountain-view";
import type { Advisory, Channel, RiskLevel } from "@/lib/types";

export interface PlanAgentChip {
  agent: string;
  fact: string;
}

export interface PlanPriorityBlock {
  rank: number;
  title: string;
  bullets: string[];
  emphasis: "critical" | "standard";
  chips: PlanAgentChip[];
}

export interface ResponsePlan {
  mountain: string;
  region: string;
  severity: RiskLevel;
  headline: string;
  serious: boolean;
  agentStrip: PlanAgentChip[];
  priorities: PlanPriorityBlock[];
  fieldBullets: string[];
  publicDraft: { title: string; line: string } | null;
}

const CHANNEL_LABEL: Record<Channel, string> = {
  newsletter: "park newsletter",
  website_banner: "park website banner",
  trailhead_signage: "trailhead signs",
  visitor_center_briefing: "visitor center briefings",
  ranger_radio: "ranger radio net",
  social_media: "official social channels",
  press_release: "press desk",
  emergency_broadcast: "emergency broadcast",
};

function isSerious(advisory: Advisory): boolean {
  const rank = advisory.response.posture_rank;
  return (
    rank >= 3 ||
    advisory.response.priority_rank >= 2 ||
    advisory.severity === "high" ||
    advisory.severity === "extreme"
  );
}

function channelList(channels: Channel[]): string {
  const labels = channels.slice(0, 4).map((c) => CHANNEL_LABEL[c]);
  if (labels.length === 0) {
    return "trailhead signage and the visitor center";
  }
  if (labels.length === 1) {
    return labels[0]!;
  }
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

function agentStrip(advisory: Advisory, agents: Record<string, PipelineAgentState>): PlanAgentChip[] {
  const chips: PlanAgentChip[] = [];
  const hazard = advisory.hazard;
  if (hazard?.drivers.length) {
    chips.push({ agent: "Terrain", fact: hazard.drivers.slice(0, 2).join("; ") });
  } else if (agents.terrain?.summary) {
    chips.push({ agent: "Terrain", fact: agents.terrain.summary });
  }
  const rain = advisory.conditions;
  if (rain) {
    chips.push({
      agent: "Weather",
      fact: `${rain.rain_past_72h_mm.toFixed(1)} mm past 72 h · ${rain.rain_next_24h_mm.toFixed(1)} mm next 24 h (${rain.source})`,
    });
  } else if (agents.weather?.summary) {
    chips.push({ agent: "Weather", fact: agents.weather.summary });
  }
  const worst = advisory.avoid[0];
  if (worst) {
    chips.push({
      agent: "Trails",
      fact: `${worst.trail} peaks at ${(worst.max_probability * 100).toFixed(0)}% on ${worst.share_at_high * 100}% of miles`,
    });
  } else if (agents.trails?.summary) {
    chips.push({ agent: "Trails", fact: agents.trails.summary });
  }
  if (agents.synthesizer?.summary) {
    chips.push({ agent: "Synthesizer", fact: agents.synthesizer.summary });
  }
  return chips.slice(0, 5);
}

function closureBullets(measures: ReactiveMeasure[]): string[] {
  return measures
    .filter((m) => m.category === "closures" && m.timing === "now")
    .slice(0, 4)
    .map((m) => m.title.replace(/^Keep hikers off /i, "Close "));
}

function coordinationBullets(measures: ReactiveMeasure[]): string[] {
  return measures
    .filter((m) => m.category === "coordination")
    .slice(0, 3)
    .map((m) => m.title);
}

/**
 * Builds a mountain-specific response plan from the finished advisory and agent row summaries.
 */
export function buildResponsePlan(
  advisory: Advisory,
  measures: ReactiveMeasure[],
  agents: Record<string, PipelineAgentState>,
  region: string,
): ResponsePlan {
  const serious = isSerious(advisory);
  const hazard = advisory.hazard;
  const channels = channelList(advisory.response.channels);
  const strip = agentStrip(advisory, agents);

  const scaleLine = hazard
    ? `${hazard.place} on ${hazard.trail ?? "mapped trails"} · model peak ${(hazard.max_probability * 100).toFixed(0)}%`
    : advisory.response.headline;

  const priorities: PlanPriorityBlock[] = serious
    ? [
        {
          rank: 1,
          title: "Alert rangers and scale the response",
          emphasis: "critical",
          chips: strip.filter((c) => c.agent === "Terrain" || c.agent === "Weather"),
          bullets: [
            `Dispatch ${advisory.response.priority} priority to field rangers: ${scaleLine}.`,
            `Staffing: ${advisory.response.staffing}`,
            `Escalate if ${advisory.response.escalate_if}`,
            ...coordinationBullets(measures),
          ],
        },
        {
          rank: 2,
          title: "Draft evacuations and hiker alerts",
          emphasis: "critical",
          chips: strip.filter((c) => c.agent === "Trails" || c.agent === "Synthesizer"),
          bullets: [
            `Push ${channels} with posture ${advisory.response.posture.replaceAll("_", " ")}.`,
            advisory.alert.hiker || advisory.alert.what,
            ...advisory.avoid.slice(0, 3).map((r) => `Avoid ${r.trail}: ${r.guidance}`),
          ],
        },
      ]
    : [
        {
          rank: 1,
          title: "Alert park rangers",
          emphasis: "standard",
          chips: strip.slice(0, 2),
          bullets: [
            `Brief rangers on ${advisory.mountain}: ${advisory.summary}`,
            hazard ? `Watch ${hazard.place} (${hazard.severity} on ${hazard.trail ?? "trails"}).` : advisory.response.headline,
            `Timeline: ${advisory.response.timeline}`,
          ],
        },
        {
          rank: 2,
          title: "Tell the community board to stay careful",
          emphasis: "standard",
          chips: strip.filter((c) => c.agent === "Trails" || c.agent === "Synthesizer"),
          bullets: [
            `Post a ${advisory.response.posture.replaceAll("_", " ")} notice via ${channels}.`,
            advisory.alert.how_to_avoid || advisory.alert.body,
            ...advisory.safe.slice(0, 2).map((r) => `Safer option: ${r.trail} — ${r.guidance}`),
          ],
        },
      ];

  const fieldBullets = [...closureBullets(measures), ...measures.filter((m) => m.category === "monitoring").map((m) => m.title)].slice(
    0,
    5,
  );

  const publicMeasure = measures.find((m) => m.category === "public");

  return {
    mountain: advisory.mountain,
    region,
    severity: advisory.severity,
    headline: advisory.response.headline,
    serious,
    agentStrip: strip,
    priorities,
    fieldBullets,
    publicDraft: publicMeasure
      ? { title: publicMeasure.title, line: publicMeasure.detail.split(/(?<=[.!?])\s+/)[0] ?? publicMeasure.detail }
      : { title: advisory.alert.title, line: advisory.alert.hiker || advisory.alert.body },
  };
}

/** Fake dispatch tasks shown after the user approves the plan. */
export function dispatchTasks(plan: ResponsePlan, advisory: Advisory): string[] {
  const tasks = [
    "Orchestrator · locking plan version",
    `Alerter · queuing ${CHANNEL_LABEL[advisory.response.channels[0] ?? "trailhead_signage"]}`,
    "Trails agent · updating closure list in ops dashboard",
    "Weather agent · attaching rain totals to the bulletin",
  ];
  if (plan.serious) {
    tasks.push("Mass channel · drafting EVACUATE language for town contacts");
    tasks.push("Maps liaison · flagging visitor POIs near downvalley channels (simulated)");
  } else {
    tasks.push("Community board · posting WATCH notice for hikers and gateway towns");
    tasks.push("Maps liaison · soft-updating trail status pins (simulated)");
  }
  tasks.push("Ranger net · dispatch notification sent (simulated)");
  return tasks;
}
