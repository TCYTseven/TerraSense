import { StatusGlyph } from "terrasense-ui";

// StatusGlyph: an agent's status as a glyph (idle circle, running dot, done check, error cross).
// Status never uses a risk color: green for done or red for failed would claim a risk level.
// Always pair it with the status word.

const STATUSES = [
  { status: "idle", word: "idle" },
  { status: "running", word: "running" },
  { status: "done", word: "done" },
  { status: "error", word: "failed" },
] as const;

/** Each status with its word, as on an agent card. */
export const Statuses = () => (
  <ul className="flex w-56 flex-col gap-3 bg-card p-5 text-base">
    {STATUSES.map(({ status, word }) => (
      <li key={status} className="flex items-center gap-3">
        <StatusGlyph status={status} />
        <span className={status === "idle" ? "text-muted-foreground" : ""}>{word}</span>
      </li>
    ))}
  </ul>
);

/** Larger, for the Orchestrator node. */
export const Large = () => (
  <div className="flex items-center gap-4 bg-card p-5">
    <StatusGlyph status="idle" className="size-5" />
    <StatusGlyph status="running" className="size-5" />
    <StatusGlyph status="done" className="size-5" />
    <StatusGlyph status="error" className="size-5" />
  </div>
);
