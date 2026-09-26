import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import MountainCard from "@/components/mountain/mountain-card";
import { getLayer, getMountain, getRiskSummary } from "@/lib/api";
import type { LayerTiles, MountainRiskSummary } from "@/lib/types";

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

/** The trail scores on the saved heat map, or null. A failed read leaves the card unscored. */
async function loadRiskSummary(slug: string): Promise<MountainRiskSummary | null> {
  try {
    return await getRiskSummary(slug);
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
    if (!mountain) {
      return { title: "Mountain not found" };
    }
    const suffix = mountain.is_live ? "Live hazard map" : "Mountain profile";
    return { title: `${mountain.name} — ${suffix}` };
  } catch {
    return { title: "Mountain unavailable" };
  }
}

/**
 * The mountain page: the 3D mountain view and the stats panel. Live mountains also get the
 * heat map layers, the top five trails, and the agents.
 */
export default async function MountainPage({ params }: PageProps<"/mountains/[slug]">) {
  const { slug } = await params;
  const mountain = await loadMountain(slug);
  if (!mountain) {
    notFound();
  }
  const susceptibility = await loadLayer(slug, "susceptibility");
  const [probability, riskSummary] = mountain.is_live
    ? await Promise.all([loadLayer(slug, "probability"), loadRiskSummary(slug)])
    : [null, null];

  return (
    <MountainCard mountain={mountain} probability={probability} susceptibility={susceptibility} riskSummary={riskSummary} />
  );
}
