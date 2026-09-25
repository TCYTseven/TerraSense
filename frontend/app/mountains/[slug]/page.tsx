import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import RiskBadge from "@/components/risk-badge";
import { getMountain } from "@/lib/api";
import { formatElevation, formatLatLon, refreshLabel } from "@/lib/format";

// One API call per request, shared by the metadata and the page.
const loadMountain = cache((slug: string) => getMountain(slug));

export async function generateMetadata({
  params,
}: PageProps<"/mountains/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  try {
    const mountain = await loadMountain(slug);
    return { title: mountain ? `${mountain.name} · TerraSense` : "Mountain not found · TerraSense" };
  } catch {
    // The page hits the same error and its error boundary explains it.
    return { title: "TerraSense" };
  }
}

/**
 * The mountain page: a map area (the Mapbox terrain view arrives in step 15) and the
 * ranger panel. Static mountains show their fixed risk and no Analyze now.
 */
export default async function MountainPage({ params }: PageProps<"/mountains/[slug]">) {
  const { slug } = await params;
  const mountain = await loadMountain(slug);
  if (!mountain) {
    notFound();
  }

  return (
    <main className="flex min-h-dvh animate-fade-in flex-col motion-reduce:animate-none lg:h-dvh lg:flex-row">
      <section
        aria-label="Terrain map"
        className="relative h-[42dvh] shrink-0 overflow-hidden border-b border-border bg-muted bg-grid lg:h-auto lg:flex-[7] lg:border-b-0 lg:border-r"
      >
        <div className="absolute inset-0 grid place-items-center">
          <div className="text-center">
            <span aria-hidden className="mx-auto mb-4 block size-3 rounded-full border border-muted-foreground" />
            <p className="font-mono text-sm text-foreground">{formatLatLon(mountain.lat, mountain.lon)}</p>
            <p className="mt-1 text-xs text-muted-foreground">Summit</p>
          </div>
        </div>
      </section>

      <aside className="flex flex-col gap-6 bg-card px-6 py-6 lg:flex-[3] lg:overflow-y-auto">
        <Link href="/" className="self-start text-sm text-primary underline decoration-1 underline-offset-3">
          ← Globe
        </Link>

        <header>
          <h1 className="text-2xl font-semibold tracking-tight">{mountain.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{mountain.region}</p>
        </header>

        <dl className="grid grid-cols-2 gap-4 border-y border-border py-4">
          <div>
            <dt className="text-xs text-muted-foreground">Elevation</dt>
            <dd className="mt-1 font-mono text-sm">{formatElevation(mountain.elevation_m)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Summit</dt>
            <dd className="mt-1 font-mono text-sm">{formatLatLon(mountain.lat, mountain.lon)}</dd>
          </div>
        </dl>

        <section aria-labelledby="risk-heading">
          <h2 id="risk-heading" className="text-xs text-muted-foreground">
            Overall risk
          </h2>
          <RiskBadge level={mountain.current_risk_level} className="mt-2 text-lg font-medium" />
          <p className="mt-1 font-mono text-xs text-muted-foreground">{refreshLabel(mountain)}</p>
          {!mountain.is_live && (
            <p className="mt-3 text-sm text-muted-foreground">
              A fixed risk for this globe marker. TerraSense runs live analysis for Mount Rainier.
            </p>
          )}
        </section>

        {mountain.is_live && (
          <div className="mt-auto">
            <button
              type="button"
              disabled
              className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              Analyze now
            </button>
            <p className="mt-2 text-xs text-muted-foreground">
              Starts the five-agent analysis once the pipeline is connected.
            </p>
          </div>
        )}
      </aside>
    </main>
  );
}
