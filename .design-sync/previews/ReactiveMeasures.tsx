import { ReactiveMeasures, type ReactiveMeasure, type TrailRisk } from "terrasense-ui";

// ReactiveMeasures: what to do after a run, grouped the way an incident is run (closures,
// evacuation and sweeps, search and rescue, field monitoring, agency coordination, public
// notice). The section takes the overall level's treatment. Every public notice is a draft.

const trail = (letter: TrailRisk["letter"], name: string, level: TrailRisk["level"]): TrailRisk => ({
  id: letter,
  letter,
  name,
  score: 0,
  level,
  slopeDeg: 0,
  primaryFactor: "",
  center: [0, 0],
  zoom: 13,
  geom: null,
});

const TRAILS = [
  trail("A", "Kautz Creek Trail", "extreme"),
  trail("B", "Van Trump Trail", "high"),
  trail("C", "Comet Falls", "high"),
];

const FULL: ReactiveMeasure[] = [
  { category: "closures", title: "Close Kautz Creek Trail", detail: "0.74 extreme, 34° with drainage channel. Gate the trailhead and post closure signs through the storm.", when: "Now", letter: "A" },
  { category: "closures", title: "Restrict Van Trump Trail to the lower miles", detail: "Hold hikers below the 36° crossings until a patrol clears them.", when: "Within 1 h", letter: "B" },
  { category: "evacuation", title: "Sweep the 4 flagged drainages", detail: "Clear backcountry camps and day hikers from Kautz Creek Trail, Van Trump Trail, Comet Falls. Turn people back at the trailheads.", when: "Now", letter: null },
  { category: "evacuation", title: "Open a shelter point at the nearest visitor center", detail: "Somewhere dry for swept hikers to check in, so rangers can account for everyone on the permit list.", when: "Within 2 h", letter: null },
  { category: "rescue", title: "Pre-stage a search and rescue team", detail: "Stage a team and litter at the Kautz Creek Trail trailhead, and confirm a helicopter can fly if the ceiling allows.", when: "Within 2 h", letter: "A" },
  { category: "monitoring", title: "Post a spotter on Van Trump Trail", detail: "Watch the crossings for fresh cracks, muddy runoff, or a sudden drop in creek flow, which can come before a debris flow. Report by radio every 30 min.", when: "Within 1 h", letter: "B" },
  { category: "coordination", title: "Brief county emergency management", detail: "Share the flagged trails and the 0.52 high level, and agree who closes the roads below the drainages.", when: "Within 1 h", letter: null },
  { category: "public", title: "Kautz Creek Trail closed", detail: "Kautz Creek Trail is closed for slide risk during heavy rain. Choose another route and stay out of creek channels.", when: "Draft", letter: "A" },
  { category: "public", title: "Caution on Comet Falls", detail: "Rain on steep ground raises slide risk on Comet Falls. Turn back if you hear rumbling or see muddy water.", when: "Draft", letter: "C" },
];

/** A High run on Rainier: every group, most urgent first. */
export const HighRun = () => (
  <div className="w-[600px] bg-card">
    <ReactiveMeasures measures={FULL} level="high" trails={TRAILS} />
  </div>
);

/** A Moderate run: fewer measures, no treatment. */
export const ModerateRun = () => (
  <div className="w-[600px] bg-card">
    <ReactiveMeasures
      measures={[
        { category: "monitoring", title: "Patrol Comet Falls after the heaviest rain", detail: "Walk it at first light and log any new slumps or downed trees at 31°.", when: "Next morning", letter: "C" },
        { category: "coordination", title: "Ask the weather service for rain updates", detail: "Request a call if the next 24 h totals rise, and re-run Analyze now when they do.", when: "Within 6 h", letter: null },
        { category: "public", title: "Caution on Comet Falls", detail: "Rain on steep ground raises slide risk on Comet Falls. Turn back if you hear rumbling or see muddy water.", when: "Draft", letter: "C" },
      ]}
      level="moderate"
      trails={TRAILS}
    />
  </div>
);
