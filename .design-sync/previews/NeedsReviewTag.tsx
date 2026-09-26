import { LevelWord, NeedsReviewTag } from "terrasense-ui";

// NeedsReviewTag: shown beside the level word when the agents' severities differ by two or
// more levels. Muted text in a 1 px border; never a risk color.

/** Beside an Extreme level inside the High/Extreme treatment. */
export const BesideExtreme = () => (
  <div className="w-[420px] bg-card">
    <div className="border-l-3 border-risk-extreme bg-risk-extreme/8 px-5 py-4">
      <p className="flex items-center gap-2">
        <LevelWord level="extreme" className="text-base font-semibold" />
        <NeedsReviewTag />
      </p>
    </div>
  </div>
);

/** Beside a Moderate level: no treatment below High. */
export const BesideModerate = () => (
  <div className="w-[420px] bg-card px-5 py-4">
    <p className="flex items-center gap-2">
      <LevelWord level="moderate" className="text-base font-semibold" />
      <NeedsReviewTag />
    </p>
  </div>
);
