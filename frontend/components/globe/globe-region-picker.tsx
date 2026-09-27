"use client";

import { GLOBE_REGIONS, type GlobeRegionId } from "@/lib/globe-regions";

/** Top-right preset views: zoom the globe to a region and stop idle spin (except whole globe). */
export default function GlobeRegionPicker({
  value,
  disabled,
  onChange,
}: {
  value: GlobeRegionId;
  disabled?: boolean;
  onChange: (id: GlobeRegionId) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className="sr-only">Globe region</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as GlobeRegionId)}
        className="rounded-md border border-border bg-popover/90 px-3 py-2 text-sm text-foreground shadow-sm backdrop-blur-sm transition-colors hover:border-primary/40 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-50"
      >
        {GLOBE_REGIONS.map((region) => (
          <option key={region.id} value={region.id}>
            {region.label}
          </option>
        ))}
      </select>
    </label>
  );
}
