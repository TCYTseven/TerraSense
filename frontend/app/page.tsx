import type { Viewport } from "next";
import GlobeView from "@/components/globe/globe-view";
import { HOME_THEME } from "@/lib/theme";

export const viewport: Viewport = {
  themeColor: HOME_THEME.background,
  colorScheme: "light",
};

/**
 * Full-screen Earth. The globe mounts in the browser because it uses WebGL.
 */
export default function Home() {
  return (
    <main className="theme-home-light relative h-dvh w-full overflow-hidden">
      <GlobeView />
      <header className="pointer-events-none absolute left-6 top-6">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          TerraSense
        </h1>
        <p className="mt-0.5 text-sm text-muted-foreground">Landslide hazard intelligence</p>
      </header>
    </main>
  );
}
