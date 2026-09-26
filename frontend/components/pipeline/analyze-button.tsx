/** The panel footer's primary action. The shell renders it in the sticky footer. */
export default function AnalyzeButton({
  running,
  onAnalyze,
  className,
}: {
  running: boolean;
  onAnalyze: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onAnalyze}
      disabled={running}
      aria-busy={running}
      className={`h-10 rounded-md bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary ${className ?? "w-full"}`}
    >
      {running ? "Analyzing…" : "Analyze now"}
    </button>
  );
}
