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

const DATE_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/** "2011-05-01" → "May 1, 2011". Dates without a time read the same everywhere. */
export function formatDate(isoDate: string): string {
  return DATE_FORMAT.format(new Date(`${isoDate}T00:00:00Z`));
}

/** A catalog value such as "debris_flow" → "Debris flow". */
export function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "46.8523° N, 121.7603° W". */
export function formatLatLon(lat: number, lon: number): string {
  const latText = `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}`;
  const lonText = `${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? "E" : "W"}`;
  return `${latText}, ${lonText}`;
}

// --- Panel values (design addendum, Units and numbers). US units; the API stays metric. -----

const FEET_PER_METER = 3.28084;
const MM_PER_INCH = 25.4;

/** 4392 m → "14,410 ft": feet, nearest 10. */
export function formatFeet(meters: number): string {
  return `${(Math.round((meters * FEET_PER_METER) / 10) * 10).toLocaleString("en-US")} ft`;
}

/** 83.2 mm → "3.28 in". */
export function formatInches(mm: number): string {
  return `${(mm / MM_PER_INCH).toFixed(2)} in`;
}

/** 0.957 → "0.96": probability, confidence, and score, two decimals and no percent. */
export function formatScore(value: number): string {
  return value.toFixed(2);
}

/** "mi 4.6–4.9": a mile range in a row. */
export function formatMileRange(start: number, end: number): string {
  return `mi ${start.toFixed(1)}–${end.toFixed(1)}`;
}

/** -1.52 km → "−0.9 mi": added distance, signed miles. */
export function formatSignedMiles(km: number): string {
  const miles = Math.round((km / KM_PER_MILE) * 10) / 10 || 0;
  return `${miles > 0 ? "+" : miles < 0 ? "−" : "±"}${Math.abs(miles).toFixed(1)} mi`;
}

/** -63 m → "−210 ft": added climb, signed feet to the nearest 10. */
export function formatSignedFeet(meters: number): string {
  const feet = Math.round((meters * FEET_PER_METER) / 10) * 10 || 0;
  return `${feet > 0 ? "+" : feet < 0 ? "−" : "±"}${Math.abs(feet).toLocaleString("en-US")} ft`;
}

const CLOCK_FORMAT = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/** "14:05": 24-hour local time, no seconds. */
export function formatClock(iso: string): string {
  return CLOCK_FORMAT.format(new Date(iso));
}

/** "12 min ago": the largest whole unit since a time. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) {
    return "just now";
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.floor(hours / 24)} days ago`;
}

/** "Debris flow" / "Landslide". */
export function hazardLabel(type: string): string {
  return type === "debris_flow" ? "Debris flow" : "Landslide";
}
