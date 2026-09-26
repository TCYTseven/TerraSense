import { PreventativeMeasures } from "terrasense-ui";

// PreventativeMeasures: three to five short things to do before the weather turns.
// One line each where they fit; plain verbs.

/** Rainier before a storm. */
export const BeforeTheStorm = () => (
  <div className="w-[600px] bg-card">
    <PreventativeMeasures
      items={[
        "Post a debris-flow advisory at the Kautz Creek and Comet Falls trailheads.",
        "Walk the Van Trump crossings after any 24-hour rain above 1 inch.",
        "Keep culverts on the Glacier Basin Trail clear before the storm.",
        "Stage closure signs at Paradise for the Skyline Trail miles.",
      ]}
    />
  </div>
);

/** A quiet day: three items. */
export const QuietDay = () => (
  <div className="w-[600px] bg-card">
    <PreventativeMeasures
      items={[
        "Check drainages on the Wonderland Trail after the next rain.",
        "Refresh the trailhead slide notice at Longmire.",
        "Log any new slumps on the Skyline Trail during routine patrols.",
      ]}
    />
  </div>
);
