import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import MountainMap from "@/components/map/mountain-map";
import RiskBadge from "@/components/risk-badge";
import { getMountain } from "@/lib/api";
import { formatElevation, formatLatLon, formatMiles, refreshLabel } from "@/lib/format";
import type { MountainDetail } from "@/lib/types";

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

/** The sentence under the overall risk. The Risk Synthesizer's summary replaces it in step 23. */
function riskSentence(mountain: MountainDetail): string {
  if (!mountain.is_live) {
    return "A fixed risk for this globe marker. TerraSense runs live analysis for Mount Rainier.";
  }
  return "Analyze now checks the next 72 hours of rain against this terrain and flags the trail miles at risk.";
}

/**
 * The mountain page: the terrain map (about 70% of the width) and the ranger panel.
 * Static mountains show their fixed risk and no Analyze now.
 */
export default async function MountainPage({ params }: PageProps<"/mountains/[slug]">) {
  const { slug } = await params;
  const mountain = await loadMountain(slug);
  if (!mountain) {
    notFound();
  }
  // The hero trail has segments: the model scores it mile by mile. The rest are context.
  const heroTrails = mountain.trails.filter((trail) => trail.segments.length > 0);
  const otherTrails = mountain.trails.filter((trail) => trail.segments.length === 0);

  return (
    <main className="flex min-h-dvh animate-fade-in flex-col motion-reduce:animate-none lg:h-dvh lg:flex-row">
      <section
        aria-label="Terrain map"
        className="relative h-[52dvh] shrink-0 overflow-hidden border-b border-line bg-surface lg:h-auto lg:flex-[7] lg:border-b-0 lg:border-r"
      >
        <MountainMap
          key={mountain.slug}
          name={mountain.name}
          lon={mountain.lon}
          lat={mountain.lat}
          elevationM={mountain.elevation_m}
          trails={mountain.trails}
        />
      </section>

      <aside className="flex flex-col gap-6 bg-panel px-6 py-6 lg:flex-[3] lg:overflow-y-auto">
        <Link href="/" className="self-start text-sm text-accent hover:underline">
          ← Globe
        </Link>

        <header>
          <h1 className="text-2xl font-semibold tracking-tight">{mountain.name}</h1>
          <p className="mt-1 text-sm text-muted">{mountain.region}</p>
        </header>

        <dl className="grid grid-cols-2 gap-4 border-y border-line py-4">
          <div>
            <dt className="text-xs text-muted">Elevation</dt>
            <dd className="mt-1 font-mono text-sm">{formatElevation(mountain.elevation_m)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Summit</dt>
            <dd className="mt-1 font-mono text-sm">{formatLatLon(mountain.lat, mountain.lon)}</dd>
          </div>
        </dl>

        <section aria-labelledby="risk-heading">
          <h2 id="risk-heading" className="text-xs text-muted">
            Overall risk
          </h2>
          <RiskBadge level={mountain.current_risk_level} className="mt-2 text-lg font-medium" />
          <p className="mt-1 font-mono text-xs text-muted">{refreshLabel(mountain)}</p>
          <p className="mt-3 text-sm text-muted">{riskSentence(mountain)}</p>
        </section>

        {mountain.trails.length > 0 && (
          <section aria-labelledby="trails-heading">
            <h2 id="trails-heading" className="text-xs text-muted">
              Trails
            </h2>
            <ul className="mt-2 divide-y divide-line border-y border-line">
              {heroTrails.map((trail) => (
                <li key={trail.id} className="flex items-baseline justify-between gap-4 py-2.5">
                  <span className="text-sm font-medium">{trail.name}</span>
                  <span className="shrink-0 font-mono text-xs text-muted">
                    {trail.length_km !== null && `${formatMiles(trail.length_km)} · `}
                    {trail.segments.length} segments
                  </span>
                </li>
              ))}
            </ul>
            {otherTrails.length > 0 && (
              <details className="group mt-2">
                <summary className="cursor-pointer text-xs text-accent hover:underline">
                  {otherTrails.length} more trails on the map
                </summary>
                <ul className="mt-2 columns-2 gap-4 text-xs text-muted">
                  {otherTrails.map((trail) => (
                    <li key={trail.id} className="break-inside-avoid py-0.5">
                      {trail.name}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        )}

        {mountain.is_live && (
          <div className="mt-auto">
            <button
              type="button"
              disabled
              className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-40"
            >
              Analyze now
            </button>
            <p className="mt-2 text-xs text-muted">
              Starts the five-agent analysis once the pipeline is connected.
            </p>
          </div>
        )}
      </aside>
    </main>
  );
}
