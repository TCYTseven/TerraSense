import { TrailList, type TrailRisk } from "terrasense-ui";

// TrailList: the top five at-risk trails, riskiest first. Each row: letter badge, name, primary
// factor and slope, level dot and mono score, and a View button that flies the map to the trail.

const TRAILS: TrailRisk[] = [
  { id: "a", letter: "A", name: "Kautz Creek Trail", score: 0.74, level: "extreme", slopeDeg: 34, primaryFactor: "Drainage channel", center: [-121.8512, 46.7783], zoom: 13.2, geom: null },
  { id: "b", letter: "B", name: "Van Trump Trail", score: 0.66, level: "high", slopeDeg: 36, primaryFactor: "Steep slopes", center: [-121.7819, 46.7917], zoom: 13.4, geom: null },
  { id: "c", letter: "C", name: "Comet Falls", score: 0.58, level: "high", slopeDeg: 31, primaryFactor: "Recent rain", center: [-121.7906, 46.7831], zoom: 13.4, geom: null },
  { id: "d", letter: "D", name: "Glacier Basin Trail", score: 0.47, level: "high", slopeDeg: 29, primaryFactor: "Sparse vegetation", center: [-121.6913, 46.8951], zoom: 13, geom: null },
  { id: "e", letter: "E", name: "Skyline Trail", score: 0.38, level: "moderate", slopeDeg: 27, primaryFactor: "Concave hollow", center: [-121.7216, 46.803], zoom: 13.2, geom: null },
];

/** The list as the panel opens: nothing viewed yet. */
export const TopFive = () => (
  <div className="w-[600px] bg-card">
    <TrailList trails={TRAILS} selected={null} onView={() => {}} />
  </div>
);

/** After View on trail B: the row takes the accent left border and the hover surface. */
export const Selected = () => (
  <div className="w-[600px] bg-card">
    <TrailList trails={TRAILS} selected="B" onView={() => {}} />
  </div>
);
