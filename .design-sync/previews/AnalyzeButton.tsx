import { AnalyzeButton } from "terrasense-ui";

// AnalyzeButton: the one action on the mountain page, pinned in the panel's footer.
// Accent fill, 40 px, full width. While a run lasts it reads "Analyzing…" and is disabled.

/** Ready: pinned in the footer. */
export const Ready = () => (
  <footer className="w-[600px] border-t border-border bg-card px-5 py-4">
    <AnalyzeButton running={false} onAnalyze={() => {}} />
  </footer>
);

/** Running: disabled at 40% opacity. */
export const Running = () => (
  <footer className="w-[600px] border-t border-border bg-card px-5 py-4">
    <AnalyzeButton running onAnalyze={() => {}} />
  </footer>
);
