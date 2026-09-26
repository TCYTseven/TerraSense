import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { THEME } from "@/lib/theme";
import "./globals.css";

/** UI text. */
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

/** Scores, miles, coordinates, and timestamps. */
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "TerraSense — Landslide hazard intelligence",
    template: "%s | TerraSense",
  },
  description:
    "Explore mountains worldwide. Landslide hazard intelligence for hikers and park rangers, live on Mount Rainier.",
  icons: {
    icon: [{ url: "/terrasenselogo.png", type: "image/png" }],
    apple: "/terrasenselogo.png",
  },
  openGraph: {
    title: "TerraSense",
    description: "Landslide hazard intelligence for hikers and park rangers.",
    images: [{ url: "/terrasenselogo.png", width: 512, height: 512, alt: "TerraSense" }],
  },
};

export const viewport: Viewport = {
  themeColor: THEME.background,
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body
        className="flex min-h-full flex-col overflow-x-hidden bg-background text-foreground"
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
