import Link from "next/link";
import { formatFeet } from "@/lib/format";
import type { HillView } from "@/lib/hill";

/** The back link, the hill's name, and one line of basic stats. */
export default function HillHeader({ hill }: { hill: HillView }) {
  const { stats } = hill;
  return (
    <header className="px-5 pb-4 pt-5">
      <Link href="/" className="text-sm text-primary underline decoration-1 underline-offset-3">
        Back to the globe
      </Link>
      <h1 className="mt-3 text-2xl/7 font-semibold tracking-[-0.01em]">{hill.name}</h1>
      <p className="mt-1.5 flex flex-wrap gap-x-3 text-base text-muted-foreground">
        <span className="font-mono text-[0.92em] text-foreground">{formatFeet(stats.elevationM)}</span>
        {hill.isLive && (
          <>
            {stats.meanSlopeDeg !== null && (
              <span>
                <span className="font-mono text-[0.92em] text-foreground">{Math.round(stats.meanSlopeDeg)}°</span> mean
                slope
              </span>
            )}
            <span>
              <span className="font-mono text-[0.92em] text-foreground">{stats.areaKm2.toLocaleString("en-US")} km²</span>
            </span>
          </>
        )}
        <span>{hill.region}</span>
      </p>
    </header>
  );
}
