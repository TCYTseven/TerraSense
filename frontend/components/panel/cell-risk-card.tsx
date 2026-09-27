"use client";

import type { PlaceKind } from "@/lib/types";
import AvalancheRiskCard, { type AvalancheRiskPanelLayout } from "./avalanche-risk-card";
import LandslideRiskCard, { type LandslideRiskPanelLayout } from "./landslide-risk-card";

export type CellRiskPanelLayout = LandslideRiskPanelLayout;

/**
 * Spot-check card under the header: mountains show avalanche (7-day projection), hills show landslide.
 */
export default function CellRiskCard({
  placeKind,
  latitude,
  longitude,
  mountainSlug,
  panelLayout = "full",
}: {
  placeKind: PlaceKind;
  latitude: number;
  longitude: number;
  mountainSlug?: string;
  panelLayout?: CellRiskPanelLayout;
}) {
  if (placeKind === "hill") {
    return (
      <LandslideRiskCard
        latitude={latitude}
        longitude={longitude}
        mountainSlug={mountainSlug}
        panelLayout={panelLayout}
      />
    );
  }
  return (
    <AvalancheRiskCard latitude={latitude} longitude={longitude} panelLayout={panelLayout as AvalancheRiskPanelLayout} />
  );
}
