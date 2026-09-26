import { ImageResponse } from "next/og";
import { THEME } from "@/lib/theme";

// The app icon: a peak over a baseline. Drawn from lib/theme.ts so the neutral
// values live only there and in globals.css.
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: THEME.background,
          borderRadius: 7,
        }}
      >
        <svg width="32" height="32" viewBox="0 0 32 32">
          <path d="M4.5 24.5 13 10l4.2 7 2.6-3.8 7.7 11.3z" fill={THEME.foreground} />
          <path
            d="M4.5 24.5h23"
            stroke={THEME.mutedForeground}
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </div>
    ),
    { ...size },
  );
}
