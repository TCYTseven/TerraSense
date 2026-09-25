import GlobeView from "@/components/globe/globe-view";

/**
 * Full-screen Earth. The globe mounts in the browser because it uses WebGL.
 */
export default function Home() {
  return (
    <main className="relative h-dvh w-full overflow-hidden bg-stage">
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
