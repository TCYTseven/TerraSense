import { RiskBadge } from "terrasense-ui";

// RiskBadge is the level with the word "risk" ("High risk"): the globe hover card's line.
// Inside the hill card panel, use LevelWord (the bare level word) instead.
// Compositions follow context/design-addendum.md: Risk mapping, Globe (Hover card), Units.

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

/** Globe hover card: panel surface, border, 8 px radius. Name and elevation, region, level, refresh line. */
export const HoverCard = () => (
  <div className="flex gap-6">
    <div className="w-64 rounded-lg border border-border bg-popover px-3.5 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">Mount Rainier</p>
        <Value>14,410 ft</Value>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">Cascade Range, Washington, USA</p>
      <RiskBadge level="moderate" className="mt-2.5 text-xs" />
      <p className="mt-1.5 text-xs text-muted-foreground">
        Updated <Value>12 min</Value> ago
      </p>
    </div>
    <div className="w-64 rounded-lg border border-border bg-popover px-3.5 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">Huascarán</p>
        <Value>22,200 ft</Value>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">Cordillera Blanca, Peru</p>
      <RiskBadge level="high" className="mt-2.5 text-xs" />
      <p className="mt-1.5 text-xs text-muted-foreground">Display marker. Not analyzed live.</p>
    </div>
  </div>
);

/** The same hover card on the light globe home: wrap the home screen in .theme-home-light. */
export const HoverCardOnHome = () => (
  <div className="theme-home-light p-6">
    <div className="w-64 rounded-lg border border-border bg-popover px-3.5 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">Mount Fuji</p>
        <Value>12,390 ft</Value>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">Honshu, Japan</p>
      <RiskBadge level="low" className="mt-2.5 text-xs" />
      <p className="mt-1.5 text-xs text-muted-foreground">Display marker. Not analyzed live.</p>
    </div>
  </div>
);
