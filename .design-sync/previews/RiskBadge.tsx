import { RiskBadge } from "terrasense-ui";

// Compositions follow context/design-addendum.md: Panel (Sections, High and Extreme),
// Risk mapping, Globe (Hover card), Type, Units and numbers, and Copy.
// Values sit in mono at 0.92em; words, level names, and labels stay in the sans.

const Value = ({ children }: { children: React.ReactNode }) => (
  <span className="font-mono text-[0.92em]">{children}</span>
);

/** Every level: the color always sits beside its level word. */
export const Levels = () => (
  <div className="flex w-64 flex-col gap-3 bg-card p-5 text-sm">
    <RiskBadge level="low" />
    <RiskBadge level="moderate" />
    <RiskBadge level="high" />
    <RiskBadge level="extreme" />
  </div>
);

/** Panel, overall risk at Moderate: level at lead size, 600, in the level color, then the one sentence. */
export const OverallRiskModerate = () => (
  <section className="w-[clamp(360px,30vw,440px)] bg-card px-5 py-4">
    <RiskBadge level="moderate" className="text-base font-semibold text-risk-moderate" />
    <p className="mt-1 text-base">
      Landslide risk MODERATE. West slope above Paradise, Skyline Trail mile 1.8 to 2.4. Confidence{" "}
      <Value>0.61</Value>.
    </p>
  </section>
);

/** Panel, overall risk at High: the 3 px left border and 8% tint mark High and Extreme. */
export const OverallRiskHigh = () => (
  <section className="w-[clamp(360px,30vw,440px)] bg-card">
    <div className="border-l-3 border-risk-high bg-risk-high/8 px-5 py-4">
      <RiskBadge level="high" className="text-base font-semibold text-risk-high" />
      <p className="mt-1 text-base">
        Debris flow risk HIGH. East fork drainage, Ridge Trail mile 4.2 to 5.1. Confidence <Value>0.82</Value>.
      </p>
    </div>
  </section>
);

/** needs_review keeps the level color and adds a tag: meta size, muted text, 1 px border. */
export const NeedsReview = () => (
  <section className="w-[clamp(360px,30vw,440px)] bg-card">
    <div className="border-l-3 border-risk-extreme bg-risk-extreme/8 px-5 py-4">
      <div className="flex items-center gap-2">
        <RiskBadge level="extreme" className="text-base font-semibold text-risk-extreme" />
        <span className="rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
          Needs review
        </span>
      </div>
      <p className="mt-1 text-base">
        Advisory. Debris flow risk EXTREME. East fork drainage, Ridge Trail mile 4.2 to 5.1. Confidence{" "}
        <Value>0.58</Value>. Confirm on site before closing.
      </p>
    </div>
  </section>
);

const TRAILS = [
  { name: "Ridge Trail", level: "high", score: "0.74", flagged: "4.2–5.1" },
  { name: "Skyline Trail", level: "moderate", score: "0.38" },
  { name: "Wonderland Trail", level: "low", score: "0.12" },
  { name: "Cedar Loop", level: "low", score: "0.08" },
] as const;

/** Panel, Trails: name left; level dot, word, and score right. The flagged range is never hidden. */
export const TrailRows = () => (
  <section className="w-[clamp(360px,30vw,440px)] bg-card px-5 py-4">
    <h2 className="text-xs text-muted-foreground">Trails</h2>
    <ul className="mt-2 flex flex-col gap-3">
      {TRAILS.map((t) => (
        <li key={t.name} className="text-sm">
          <div className="flex items-baseline justify-between gap-4">
            <span className="truncate">{t.name}</span>
            <span className="flex shrink-0 items-baseline gap-2">
              <RiskBadge level={t.level} />
              <Value>{t.score}</Value>
            </span>
          </div>
          {"flagged" in t && (
            <p className="text-xs text-muted-foreground">
              Flagged <Value>mi {t.flagged}</Value>
            </p>
          )}
        </li>
      ))}
    </ul>
  </section>
);

/** Globe hover card: panel surface, border, 8 px radius, 12 px padding. Name, level, refresh line. */
export const HoverCard = () => (
  <div className="flex gap-6">
    <div className="w-64 rounded-lg border border-border bg-popover p-3">
      <p className="text-sm font-semibold">Mount Rainier</p>
      <RiskBadge level="high" className="mt-1 text-xs" />
      <p className="mt-1 text-xs text-muted-foreground">
        Updated <Value>12 min</Value> ago
      </p>
    </div>
    <div className="w-64 rounded-lg border border-border bg-popover p-3">
      <p className="text-sm font-semibold">Mount Hood</p>
      <RiskBadge level="low" className="mt-1 text-xs" />
      <p className="mt-1 text-xs text-muted-foreground">Display marker. Not analyzed live.</p>
    </div>
  </div>
);
