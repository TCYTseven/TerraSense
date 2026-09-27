import type { Metadata } from "next";

/** Same asset as the home header mark and Open Graph image. */
export const SITE_ICON_PATH = "/terrasenselogo.png";

/** Favicon and touch icon on every route (merged from the root layout). */
export const siteIcons: NonNullable<Metadata["icons"]> = {
  icon: [
    { url: SITE_ICON_PATH, type: "image/png" },
    { url: SITE_ICON_PATH, type: "image/png", sizes: "512x512" },
  ],
  apple: [{ url: SITE_ICON_PATH, type: "image/png" }],
  shortcut: SITE_ICON_PATH,
};
