import { CheckIcon, CircleIcon, XIcon } from "@/components/icons";
import type { PipelineStatus } from "@/lib/mountain-view";

export const STATUS_WORDS: Record<PipelineStatus, string> = {
  idle: "idle",
  running: "running",
  done: "done",
  error: "failed",
};

/** Status never uses a risk color: green or red here would claim a risk level. */
export default function StatusGlyph({ status, className = "size-4" }: { status: PipelineStatus; className?: string }) {
  switch (status) {
    case "running":
      return (
        <span aria-hidden className={`grid place-items-center ${className}`}>
          <span className="size-2 rounded-full bg-foreground" />
        </span>
      );
    case "done":
      return <CheckIcon className={`${className} text-foreground`} />;
    case "error":
      return <XIcon className={`${className} text-foreground`} />;
    default:
      return <CircleIcon className={`${className} text-muted-foreground`} />;
  }
}
