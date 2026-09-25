import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import MountainDashboard from "@/components/mountain/mountain-dashboard";
import { getLayer, getMountain, getRun } from "@/lib/api";
import type { LayerTiles, Run } from "@/lib/types";

// One API call per request, shared by the metadata and the page.
const loadMountain = cache((slug: string) => getMountain(slug));

/** A raster layer's tiles, or null. A layer that fails to load leaves the map without it. */
async function loadLayer(slug: string, layer: string): Promise<LayerTiles | null> {
  try {
    return await getLayer(slug, layer);
  } catch {
    return null;
  }
}

/** A run for the agent rows and the reasoning panel, or null when there is none to show. */
async function loadRun(runId: string | null): Promise<Run | null> {
  if (!runId) {
    return null;
  }
  try {
    return await getRun(runId);
  } catch {
    return null;
  }
}

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
 * The mountain page: the terrain map (about 70% of the width) and the ranger panel. Live
 * mountains also get the heat map, the agents, and the reasoning panel.
 */
export default async function MountainPage({ params }: PageProps<"/mountains/[slug]">) {
  const { slug } = await params;
  const mountain = await loadMountain(slug);
  if (!mountain) {
    notFound();
  }
  // Static mountains have no raster layers and no runs.
  const [probability, susceptibility, run] = mountain.is_live
    ? await Promise.all([
        loadLayer(slug, "probability"),
        loadLayer(slug, "susceptibility"),
        loadRun(mountain.active_run_id ?? mountain.active_hazard?.run_id ?? null),
      ])
    : [null, null, null];

  return (
    <MountainDashboard
      mountain={mountain}
      probability={probability}
      susceptibility={susceptibility}
      run={run}
    />
  );
}
