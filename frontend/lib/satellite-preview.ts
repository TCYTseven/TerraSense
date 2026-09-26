import type { Mountain } from "@/lib/types";

const prefetched = new Set<string>();

/**
 * Smaller Esri export for the globe hover card (~220 px wide). Full-size URLs stay in the API/DB.
 */
export function satellitePreviewUrl(url: string): string {
  try {
    const parsed = new URL(url);
    if (
      parsed.hostname.endsWith("arcgisonline.com") &&
      parsed.pathname.includes("World_Imagery")
    ) {
      parsed.searchParams.set("size", "256,256");
      parsed.searchParams.set("compressionQuality", "75");
      return parsed.toString();
    }
  } catch {
    // Not a parseable URL; use as-is.
  }
  return url;
}

/** Warm the browser cache for one preview URL (deduped by original API URL). */
export function prefetchSatellitePreview(url: string | null | undefined): void {
  if (!url || prefetched.has(url)) {
    return;
  }
  prefetched.add(url);
  const img = new Image();
  img.decoding = "async";
  img.src = satellitePreviewUrl(url);
}

/** After the globe marker set is known, prefetch previews when the main thread is idle. */
export function prefetchSatellitePreviews(
  mountains: readonly Pick<Mountain, "satellite_image_url">[],
): void {
  const run = () => {
    for (const mountain of mountains) {
      prefetchSatellitePreview(mountain.satellite_image_url);
    }
  };
  if (typeof requestIdleCallback !== "undefined") {
    requestIdleCallback(run, { timeout: 3000 });
  } else {
    setTimeout(run, 100);
  }
}
