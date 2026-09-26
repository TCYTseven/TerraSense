/** Starts a runout, or replays the frames already loaded. Sits beside Analyze now. */
export default function SimulateButton({
  phase,
  onSimulate,
  onReplay,
}: {
  phase: "idle" | "loading" | "playing" | "finished" | "error";
  onSimulate: () => void;
  onReplay: () => void;
}) {
  const busy = phase === "loading" || phase === "playing";
  const finished = phase === "finished";
  return (
    <button
      type="button"
      onClick={finished ? onReplay : onSimulate}
      disabled={busy}
      aria-busy={busy}
      className={
        finished
          ? "h-10 flex-1 rounded-md border border-border bg-card text-sm font-medium text-foreground disabled:opacity-40"
          : "h-10 flex-1 rounded-md bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
      }
    >
      {busy ? "Simulating…" : finished ? "Replay" : "Simulate"}
    </button>
  );
}
