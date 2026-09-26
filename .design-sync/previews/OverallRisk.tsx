import { OverallRisk, type HillView } from "terrasense-ui";

// OverallRisk: the hill card's overall score (large mono, two decimals) and level word.
// High and Extreme take the 3 px border and 8% tint. Static mountains show their fixed level only.
// The panel is about 45% of the page; its sections sit on bg-card.

const rainier = (score: number, level: HillView["risk"]["level"]): HillView => ({
  slug: "mount-rainier",
  name: "Mount Rainier",
  region: "Cascade Range, Washington, USA",
  isLive: true,
  stats: { elevationM: 4392, meanSlopeDeg: 24, areaKm2: 660 },
  risk: { score, level },
  trails: [],
  preventative: [],
  isDemo: false,
});

/** Live mountain at High: the treatment marks it. */
export const High = () => (
  <div className="w-[600px] bg-card">
    <OverallRisk hill={rainier(0.52, "high")} />
  </div>
);

/** Extreme, with the illustrative-scores line that shows while numbers are not model output. */
export const ExtremeIllustrative = () => (
  <div className="w-[600px] bg-card">
    <OverallRisk hill={{ ...rainier(0.81, "extreme"), isDemo: true }} />
  </div>
);

/** Moderate: no treatment below High. */
export const Moderate = () => (
  <div className="w-[600px] bg-card">
    <OverallRisk hill={rainier(0.31, "moderate")} />
  </div>
);

/** A static display marker: the fixed level and one line, no score. */
export const StaticMountain = () => (
  <div className="w-[600px] bg-card">
    <OverallRisk
      hill={{
        slug: "mount-fuji",
        name: "Mount Fuji",
        region: "Honshu, Japan",
        isLive: false,
        stats: { elevationM: 3776, meanSlopeDeg: 0, areaKm2: 0 },
        risk: { score: 0, level: "low" },
        trails: [],
        preventative: [],
        isDemo: false,
      }}
    />
  </div>
);
