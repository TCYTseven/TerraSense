import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import MountainCard from "@/components/mountain/mountain-card";
import { getHill, getHillLayer, getHillRiskSummary } from "@/lib/api";
import type { LayerTiles, MountainRiskSummary } from "@/lib/types";

const loadHill = cache((slug: string) => getHill(slug));

async function loadLayer(slug: string, layer: string): Promise<LayerTiles | null> {
  try {
    return await getHillLayer(slug, layer);
  } catch {
    return null;
  }
}

async function loadRiskSummary(slug: string): Promise<MountainRiskSummary | null> {
  try {
    return await getHillRiskSummary(slug);
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: PageProps<"/hills/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  try {
    const hill = await loadHill(slug);
    if (!hill) {
      return { title: "Hill not found" };
    }
    const suffix = hill.is_live ? "Live hazard map" : "Hill profile";
    return { title: `${hill.name} — ${suffix}` };
  } catch {
    return { title: "Hill unavailable" };
  }
}

/**
 * The hill page: the same split as the mountain page, with the agents left idle.
 * Nothing here starts an analysis run.
 */
export default async function HillPage({ params }: PageProps<"/hills/[slug]">) {
  const { slug } = await params;
  const hill = await loadHill(slug);
  if (!hill) {
    notFound();
  }
  const susceptibility = await loadLayer(slug, "susceptibility");
  const [probability, riskSummary] = hill.is_live
    ? await Promise.all([loadLayer(slug, "probability"), loadRiskSummary(slug)])
    : [null, null];

  return (
    <MountainCard
      mountain={hill}
      probability={probability}
      susceptibility={susceptibility}
      riskSummary={riskSummary}
    />
  );
}
