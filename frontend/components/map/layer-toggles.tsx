export interface LayerToggle {
  id: string;
  label: string;
  on: boolean;
  /** Why the toggle is off limits, such as a layer that is not rendered yet. */
  unavailable?: string;
}

/**
 * The layer toggles over the lower left of the map. The one-week probability heat map is
 * the page's default layer and has no toggle.
 */
export default function LayerToggles({
  toggles,
  onToggle,
}: {
  toggles: LayerToggle[];
  onToggle: (id: string) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Map layers"
      className="absolute bottom-4 left-4 z-10 flex flex-col gap-1 rounded-lg border border-border bg-popover p-1"
    >
      {toggles.map((toggle) => (
        <button
          key={toggle.id}
          type="button"
          aria-pressed={toggle.on}
          disabled={Boolean(toggle.unavailable)}
          title={toggle.unavailable}
          onClick={() => onToggle(toggle.id)}
          className={`h-8 rounded-md border px-3 text-left text-xs ${
            toggle.on ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:bg-accent"
          } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent`}
        >
          {toggle.label}
        </button>
      ))}
    </div>
  );
}
