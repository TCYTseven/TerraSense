"use client";

import dynamic from "next/dynamic";

const SpinningGlobe = dynamic(() => import("./spinning-globe"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-background" />,
});

/**
 * Browser-only globe. WebGL cannot render during server rendering.
 */
export default function GlobeView() {
  return <SpinningGlobe />;
}
