import GlobeView from "@/components/globe/globe-view";

/**
 * Full-screen Earth. The globe mounts in the browser because it uses WebGL.
 */
export default function Home() {
  return (
    <main className="relative h-dvh w-full overflow-hidden bg-[#0A0E14]">
      <GlobeView />
      <div className="pointer-events-none absolute left-6 top-6">
        <p className="font-mono text-xs tracking-[0.28em] text-[#22D3EE]">
          TERRASENSE
        </p>
        <h1 className="mt-1 text-sm text-[#8B949E]">
          Landslide hazard intelligence
        </h1>
      </div>
    </main>
  );
}
