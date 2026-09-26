"use client";

import type { MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { CAMERA } from "./map-style";

/**
 * A slow turn around the mountain while nobody is using the map. It pauses while the pointer is
 * over the map, stops on a drag, zoom, or key press and picks up again after `CAMERA.orbitResumeMs`
 * of quiet, and stays off once a trail is focused (the camera is showing that route). No orbit
 * under prefers-reduced-motion.
 */
export function useIdleOrbit(map: MapLibreMap | null, focused: boolean) {
  useEffect(() => {
    if (!map || focused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const container = map.getContainer();
    let frame = 0;
    let last = 0;
    let hovering = false;
    let quietUntil = 0;

    const tick = (now: number) => {
      const dt = last ? Math.min(now - last, 100) : 0;
      last = now;
      // Only turn a camera that is at rest: never fight a gesture or a flight.
      if (!hovering && now >= quietUntil && !map.isMoving()) {
        map.setBearing(map.getBearing() + (CAMERA.orbitDegPerSec * dt) / 1000);
      }
      frame = requestAnimationFrame(tick);
    };
    const enter = () => {
      hovering = true;
    };
    const leave = () => {
      hovering = false;
    };
    const interact = () => {
      quietUntil = performance.now() + CAMERA.orbitResumeMs;
    };

    container.addEventListener("pointerenter", enter);
    container.addEventListener("pointerleave", leave);
    container.addEventListener("pointerdown", interact);
    container.addEventListener("wheel", interact, { passive: true });
    container.addEventListener("keydown", interact);
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      container.removeEventListener("pointerenter", enter);
      container.removeEventListener("pointerleave", leave);
      container.removeEventListener("pointerdown", interact);
      container.removeEventListener("wheel", interact);
      container.removeEventListener("keydown", interact);
    };
  }, [map, focused]);
}
