"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { getMountains } from "@/lib/api";
import type { Mountain } from "@/lib/types";

const SpinningGlobe = dynamic(() => import("./spinning-globe"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-background" />,
});

type LoadState =
  | { status: "loading" }
  | { status: "ready"; mountains: Mountain[] }
  | { status: "error" };

/**
 * Browser-only globe with the mountains from GET /mountains. WebGL cannot render
 * during server rendering.
 */
export default function GlobeView() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getMountains({ signal: controller.signal })
      .then((mountains) => setState({ status: "ready", mountains }))
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ status: "error" });
        }
      });
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setState({ status: "loading" });
    setAttempt((count) => count + 1);
  }

  return (
    <>
      <SpinningGlobe mountains={state.status === "ready" ? state.mountains : []} />
      {state.status === "error" && (
        <div className="absolute inset-x-0 bottom-8 flex justify-center px-4">
          <p
            role="alert"
            className="flex items-center gap-3 rounded-md border border-line bg-panel/90 px-4 py-2 text-sm text-muted"
          >
            Could not load mountains from the API.
            <button type="button" onClick={retry} className="font-medium text-accent hover:underline">
              Retry
            </button>
          </p>
        </div>
      )}
    </>
  );
}
