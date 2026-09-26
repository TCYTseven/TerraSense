import { LevelWord, NeedsReviewTag } from "terrasense-ui";

// LevelWord: a level dot and the bare level word in the level color. The color never
// carries the level alone. Size and weight come from className.

/** The four levels at body size. */
export const Levels = () => (
  <div className="flex w-64 flex-col gap-3 bg-card p-5 text-base">
    <LevelWord level="low" />
    <LevelWord level="moderate" />
    <LevelWord level="high" />
    <LevelWord level="extreme" />
  </div>
);

/** Beside a mono score, as in the overall risk block and the trail rows. */
export const WithScore = () => (
  <div className="flex w-[420px] flex-col gap-4 bg-card p-5">
    <p className="flex items-baseline gap-3">
      <span className="font-mono text-4xl/10 font-semibold tracking-tight">0.74</span>
      <LevelWord level="extreme" className="text-base font-semibold" />
    </p>
    <p className="flex items-baseline gap-3">
      <span className="font-mono text-4xl/10 font-semibold tracking-tight">0.38</span>
      <LevelWord level="moderate" className="text-base font-semibold" />
    </p>
  </div>
);

/** When the agents disagree by two or more levels, the tag sits beside the level word. */
export const NeedsReview = () => (
  <div className="w-[420px] bg-card">
    <div className="border-l-3 border-risk-high bg-risk-high/8 px-5 py-4">
      <p className="flex items-center gap-2">
        <LevelWord level="high" className="text-base font-semibold" />
        <NeedsReviewTag />
      </p>
      <p className="mt-2 text-sm text-muted-foreground">Agents disagree on severity, so this goes out as an advisory.</p>
    </div>
  </div>
);
