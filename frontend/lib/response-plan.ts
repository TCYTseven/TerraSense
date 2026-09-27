import type { PipelineAgentState, ReactiveMeasure } from "@/lib/mountain-view";
import type { Advisory, Channel, RiskLevel } from "@/lib/types";

export interface PlanStat {
  label: string;
  value: string;
}

export interface PlanAction {
  text: string;
}

export interface PlanPriorityBlock {
  rank: number;
  title: string;
  emphasis: "critical" | "standard";
  actions: PlanAction[];
}

export interface ResponsePlan {
  mountain: string;
  region: string;
  severity: RiskLevel;
  modeLabel: string;
  heroLine: string;
  serious: boolean;
  stats: PlanStat[];
  analysisSeconds: number | null;
  priorities: PlanPriorityBlock[];
  fieldTags: string[];
}

const CHANNEL_LABEL: Record<Channel, string> = {
  newsletter: "Newsletter",
  website_banner: "Web",
  trailhead_signage: "Trailheads",
  visitor_center_briefing: "Visitor center",
  ranger_radio: "Ranger radio",
  social_media: "Social",
  press_release: "Press",
  emergency_broadcast: "EAS",
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

function clip(text: string, max: number): string {
  const one = text.replace(/\s+/g, " ").trim();
  if (one.length <= max) {
    return one;
  }
  return `${one.slice(0, max - 1).trimEnd()}…`;
}

/** Judge-facing: one short phrase per LLM action, not full sentences. */
function compressAction(text: string): string {
  let t = text.replace(/\s+/g, " ").trim();
  t = t.replace(/^(Field rangers?|Visitor center staff|Patrol rangers?)\s+/i, "");
  const chunk = t.split(/[;]/)[0] ?? t;
  return clip(chunk, 96);
}

function uniqueActions(raw: string[], limit: number): PlanAction[] {
  const seen = new Set<string>();
  const out: PlanAction[] = [];
  for (const line of raw) {
    const text = compressAction(line);
    const key = text.toLowerCase();
    if (!text || seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push({ text });
    if (out.length >= limit) {
      break;
    }
  }
  return out;
}

function measureTags(measures: ReactiveMeasure[]): string[] {
  return measures
    .filter((m) => m.category === "closures" && m.timing === "now")
    .map((m) => clip(m.title.replace(/^Keep hikers off /i, ""), 28))
    .slice(0, 3);
}

function buildStats(advisory: Advisory): PlanStat[] {
  const hazard = advisory.hazard;
  const rain = advisory.conditions;
  const stats: PlanStat[] = [];
  if (hazard) {
    stats.push({ label: "Hotspot", value: clip(hazard.place, 34) });
    stats.push({ label: "Peak", value: `${Math.round(hazard.max_probability * 100)}%` });
  }
  if (rain) {
    stats.push({ label: "Rain 72h", value: `${Math.round(rain.rain_past_72h_mm)} mm` });
  } else if (advisory.avoid[0]) {
    stats.push({ label: "Focus trail", value: clip(advisory.avoid[0].trail, 18) });
  }
  return stats.slice(0, 3);
}

function heroLine(advisory: Advisory): string {
  const h = advisory.hazard;
  if (h) {
    const miles =
      h.start_mile != null && h.end_mile != null ? ` · mi ${h.start_mile}–${h.end_mile}` : "";
    return clip(`${h.type.replace("_", " ")} · ${h.place}${miles}`, 64);
  }
  return clip(advisory.summary, 64);
}

function analysisSeconds(agents: Record<string, PipelineAgentState>): number | null {
  const rows = Object.values(agents);
  const starts = rows.map((a) => a.startedAt).filter((t): t is number => t != null);
  const ends = rows.map((a) => a.finishedAt).filter((t): t is number => t != null);
  if (starts.length === 0 || ends.length === 0) {
    return null;
  }
  return Math.round((Math.max(...ends) - Math.min(...starts)) / 100) / 10;
}

function splitActions(actions: string[]): [string[], string[]] {
  if (actions.length <= 2) {
    return [actions, []];
  }
  const mid = Math.ceil(actions.length / 2);
  return [actions.slice(0, mid), actions.slice(mid)];
}

/**
 * Builds a minimal pitch plan from the server advisory (LLM actions, heavily shortened for UI).
 */
export function buildResponsePlan(
  advisory: Advisory,
  measures: ReactiveMeasure[],
  agents: Record<string, PipelineAgentState>,
  _region: string,
): ResponsePlan {
  const serious = isSerious(advisory);
  const llm = advisory.response.actions;
  const [forRangers, forPublic] = splitActions(llm);

  const rangersFallback = serious
    ? [clip(advisory.response.staffing, 96), clip(advisory.response.escalate_if, 96)]
    : [clip(advisory.response.timeline, 96)];

  const publicFallback = serious
    ? [
        advisory.alert.hiker ? compressAction(advisory.alert.hiker) : compressAction(advisory.alert.what),
        advisory.avoid[0] ? `Limit ${clip(advisory.avoid[0].trail, 20)}` : "",
      ]
    : [
        compressAction(advisory.alert.how_to_avoid || advisory.alert.body),
        advisory.safe[0] ? `Prefer ${clip(advisory.safe[0].trail, 20)}` : "",
      ];

  const channelHint = advisory.response.channels[0]
    ? CHANNEL_LABEL[advisory.response.channels[0]]
    : "Trailheads";

  const priorities: PlanPriorityBlock[] = serious
    ? [
        {
          rank: 1,
          title: "Rangers · scale up",
          emphasis: "critical",
          actions: uniqueActions([...forRangers, ...rangersFallback.filter(Boolean)], 2),
        },
        {
          rank: 2,
          title: "Public · evacuate & alert",
          emphasis: "critical",
          actions: uniqueActions(
            [...forPublic, ...publicFallback.filter(Boolean), `Notify via ${channelHint}`],
            2,
          ),
        },
      ]
    : [
        {
          rank: 1,
          title: "Rangers · brief & patrol",
          emphasis: "standard",
          actions: uniqueActions([...forRangers, ...rangersFallback.filter(Boolean)], 2),
        },
        {
          rank: 2,
          title: "Community · stay careful",
          emphasis: "standard",
          actions: uniqueActions([...forPublic, ...publicFallback.filter(Boolean)], 2),
        },
      ];

  return {
    mountain: advisory.mountain,
    region: _region,
    severity: advisory.severity,
    modeLabel: serious ? "Elevated response" : "Watchful response",
    heroLine: heroLine(advisory),
    serious,
    stats: buildStats(advisory),
    analysisSeconds: analysisSeconds(agents),
    priorities,
    fieldTags: measureTags(measures),
  };
}
