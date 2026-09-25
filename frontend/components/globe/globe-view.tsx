"use client";

import dynamic from "next/dynamic";
import { useEffect } from "react";
import { getMountains } from "@/lib/api";

const SpinningGlobe = dynamic(() => import("./spinning-globe"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-background" />,
});

/**
 * Browser-only globe. WebGL cannot render during server rendering.
 */
export default function GlobeView() {
  useEffect(() => {
    const controller = new AbortController();
    getMountains({ signal: controller.signal })
      .then((mountains) => {
        console.info(`TerraSense: ${mountains.length} mountains from the API`, mountains);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.error("TerraSense: could not load mountains", error);
        }
      });
    return () => controller.abort();
  }, []);

  return <SpinningGlobe />;
}
