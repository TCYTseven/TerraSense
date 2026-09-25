import type { Mountain, RiskLevel } from "./types";

/** "moderate" → "Moderate". */
export function riskLabel(level: RiskLevel): string {
  return level.charAt(0).toUpperCase() + level.slice(1);
}

const UTC_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

/** "Sep 25, 10:50 UTC". UTC so the server and the browser print the same text. */
export function formatUtc(iso: string): string {
  return `${UTC_FORMAT.format(new Date(iso))} UTC`;
}

/** The last-refresh line for a mountain. Static mountains never refresh. */
export function refreshLabel(mountain: Pick<Mountain, "is_live" | "last_analyzed_at">): string {
  if (!mountain.is_live) {
    return "Static marker, fixed risk";
  }
  if (!mountain.last_analyzed_at) {
    return "Not analyzed yet";
  }
  return `Analyzed ${formatUtc(mountain.last_analyzed_at)}`;
}

/** "4,392 m". */
export function formatElevation(meters: number): string {
  return `${meters.toLocaleString("en-US")} m`;
}

const KM_PER_MILE = 1.609344;

/** 6.4 km → "4.0 mi". Trail distances read in miles, like the mile markers. */
export function formatMiles(km: number): string {
  return `${(km / KM_PER_MILE).toFixed(1)} mi`;
}

/** "46.8523° N, 121.7603° W". */
export function formatLatLon(lat: number, lon: number): string {
  const latText = `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}`;
  const lonText = `${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? "E" : "W"}`;
  return `${latText}, ${lonText}`;
}
