import { TrailBadge } from "terrasense-ui";

// TrailBadge: a trail's letter (A–E, riskiest first) in a circle of its level color with dark
// text. The map marker for the same trail is the same circle, so a row and its marker read as one.

/** A to E across the four levels. */
export const Letters = () => (
  <div className="flex w-fit items-center gap-3 bg-card p-5">
    <TrailBadge letter="A" level="extreme" />
    <TrailBadge letter="B" level="high" />
    <TrailBadge letter="C" level="high" />
    <TrailBadge letter="D" level="moderate" />
    <TrailBadge letter="E" level="low" />
  </div>
);

/** Beside a trail name, as in a measure or a list. */
export const WithName = () => (
  <ul className="flex w-72 flex-col gap-2.5 bg-card p-5 text-base">
    <li className="flex items-center gap-3">
      <TrailBadge letter="A" level="extreme" />
      Kautz Creek Trail
    </li>
    <li className="flex items-center gap-3">
      <TrailBadge letter="B" level="high" />
      Van Trump Trail
    </li>
    <li className="flex items-center gap-3">
      <TrailBadge letter="E" level="moderate" />
      Skyline Trail
    </li>
  </ul>
);
