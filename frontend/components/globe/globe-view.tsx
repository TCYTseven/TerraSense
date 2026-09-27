"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getMountains } from "@/lib/api";
import { selectGlobeMountains } from "@/lib/globe-display-mountains";
import { globeRegionById, type GlobeRegionId } from "@/lib/globe-regions";
import { prefetchSatellitePreviews } from "@/lib/satellite-preview";
import { HOME_THEME } from "@/lib/theme";
import type { Mountain } from "@/lib/types";
import { FADE_OUT_MS, FLY_DURATION_MS } from "./motion";
import GlobeRegionPicker from "./globe-region-picker";
import MountainSearch from "./mountain-search";

const GLOBE_SPIN_PAUSE_MS = 5000;

const SpinningGlobe = dynamic(() => import("./spinning-globe"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-background" />,
});

type LoadState =
  | { status: "loading" }
  | { status: "ready"; mountains: Mountain[] }
  | { status: "error" };

/**
 * The globe screen: one marker per GET /mountains row, search over the same list, and the fly-in.
 * A marker click or a search pick flies the camera to the place, fading to the page
 * background over the last part of the flight, then opens /hills/[slug] or /mountains/[slug].
 * The globe is browser-only because WebGL cannot render during server rendering.
 */
export default function GlobeView() {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [flyTarget, setFlyTarget] = useState<Mountain | null>(null);
  const [globeReady, setGlobeReady] = useState(false);
  const [regionId, setRegionId] = useState<GlobeRegionId>("world");
  const [spinPaused, setSpinPaused] = useState(false);
  const leaving = useRef(false);
  const spinPauseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleGlobeReady = useCallback(() => setGlobeReady(true), []);
  const region = useMemo(() => globeRegionById(regionId), [regionId]);

  const pauseGlobeSpin = useCallback(() => {
    setSpinPaused(true);
    if (spinPauseTimer.current) {
      clearTimeout(spinPauseTimer.current);
    }
    spinPauseTimer.current = setTimeout(() => {
      setSpinPaused(false);
      spinPauseTimer.current = null;
    }, GLOBE_SPIN_PAUSE_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (spinPauseTimer.current) {
        clearTimeout(spinPauseTimer.current);
      }
    };
  }, []);

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

  const allMountains = state.status === "ready" ? state.mountains : [];
  const globeMountains = useMemo(() => selectGlobeMountains(allMountains), [allMountains]);

  useEffect(() => {
    if (globeMountains.length > 0) {
      prefetchSatellitePreviews(globeMountains);
    }
  }, [globeMountains]);

  function retry() {
    setState({ status: "loading" });
    setAttempt((count) => count + 1);
  }

  function placeHref(mountain: Mountain): string {
    return mountain.kind === "hill" ? `/hills/${mountain.slug}` : `/mountains/${mountain.slug}`;
  }

  function flyTo(mountain: Mountain) {
    if (flyTarget || leaving.current) {
      return;
    }
    const href = placeHref(mountain);
    if (!globeReady) {
      // The textured globe is not on screen yet, so there is nothing to fly over.
      leaving.current = true;
      router.push(href);
      return;
    }
    router.prefetch(href);
    setFlyTarget(mountain);
  }

  function arrive(mountain: Mountain) {
    if (leaving.current) {
      return;
    }
    leaving.current = true;
    setFlyTarget(null);
    // Let the globe release WebGL before MapLibre opens on the mountain page.
    window.requestAnimationFrame(() => {
      router.push(placeHref(mountain));
    });
  }

  return (
    <>
      <SpinningGlobe
        mountains={globeMountains}
        flyTarget={flyTarget}
        onSelect={flyTo}
        onArrive={arrive}
        onReady={handleGlobeReady}
        region={region}
        spinPaused={spinPaused}
        onGlobeEngage={pauseGlobeSpin}
        sceneBackground={HOME_THEME.muted}
        atmosphereColor={HOME_THEME.atmosphere}
      />
      <div className="absolute right-4 top-5 z-10 lg:right-6">
        <GlobeRegionPicker value={regionId} disabled={flyTarget !== null} onChange={setRegionId} />
      </div>
      <div className="absolute inset-x-0 top-24 z-10 mx-auto w-[min(26rem,calc(100%-2rem))] lg:top-5">
        <MountainSearch
          mountains={allMountains}
          emptyMessage={
            state.status === "error" ? "Could not load mountains." : "Mountains are still loading."
          }
          disabled={flyTarget !== null}
          onSelect={flyTo}
        />
      </div>
      {state.status === "error" && (
        <div className="absolute inset-x-0 bottom-8 flex justify-center px-4">
          <p
            role="alert"
            className="flex items-center gap-3 rounded-md border border-border bg-popover/90 px-4 py-2 text-sm text-muted-foreground"
          >
            Could not load mountains from the API.
            <button type="button" onClick={retry} className="font-medium text-primary underline decoration-1 underline-offset-3">
              Retry
            </button>
          </p>
        </div>
      )}
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-0 z-20 bg-background transition-opacity ease-in motion-reduce:transition-none ${
          flyTarget ? "opacity-100" : "opacity-0"
        }`}
        style={{
          transitionDuration: `${FADE_OUT_MS}ms`,
          transitionDelay: flyTarget ? `${FLY_DURATION_MS - FADE_OUT_MS}ms` : "0ms",
        }}
      />
    </>
  );
}
