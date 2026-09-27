"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { type RefObject, useEffect, useRef } from "react";
import { type Mesh, Quaternion, Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { GlobeRegion } from "@/lib/globe-regions";
import { latLonToVector3 } from "./geo";

/** Pull back outside the normal zoom band so the camera arcs around the hull, not through it. */
const RETREAT_DISTANCE = 4.2;
const TRANSITION_MS = 3200;

const scratchDir = new Vector3();
const scratchQuat = new Quaternion();
const scratchStartQuat = new Quaternion();
const scratchEndQuat = new Quaternion();
const scratchAxis = new Vector3(0, 0, 1);

/** Perlin-style smoothstep for C¹ continuity at endpoints. */
function smootherStep(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x * x * x * (x * (x * 6 - 15) + 10);
}

/** Unit vector from the globe center toward the camera for a preset. */
function viewDirection(region: GlobeRegion, target: Vector3): Vector3 {
  if (region.id === "world") {
    return target.set(0, 0.25, 1).normalize();
  }
  return latLonToVector3(region.lat, region.lon, 1).normalize();
}

function cameraPosition(region: GlobeRegion, direction: Vector3, distance: number, target: Vector3): Vector3 {
  if (region.id === "world") {
    return target.set(0, 0.25 * (distance / region.distance), distance);
  }
  return target.copy(direction).multiplyScalar(distance);
}

function slerpDirection(from: Vector3, to: Vector3, t: number, out: Vector3): Vector3 {
  scratchStartQuat.setFromUnitVectors(scratchAxis, from);
  scratchEndQuat.setFromUnitVectors(scratchAxis, to);
  scratchQuat.copy(scratchStartQuat).slerp(scratchEndQuat, smootherStep(t));
  return out.copy(scratchAxis).applyQuaternion(scratchQuat).normalize();
}

/** Distance eases out, holds wide, then eases in — one continuous curve, no phase seams. */
function transitionDistance(u: number, startDistance: number, endDistance: number): number {
  const peak = RETREAT_DISTANCE;
  if (u < 0.32) {
    const t = smootherStep(u / 0.32);
    return startDistance + (peak - startDistance) * t;
  }
  if (u < 0.58) {
    return peak;
  }
  const t = smootherStep((u - 0.58) / 0.42);
  return peak + (endDistance - peak) * t;
}

/** Bearing change runs mostly while the camera is pulled back. */
function transitionDirectionT(u: number): number {
  return smootherStep(Math.min(1, Math.max(0, (u - 0.18) / 0.72)));
}

interface Transition {
  startedAt: number;
  startDistance: number;
  startDirection: Vector3;
  endDirection: Vector3;
  endDistance: number;
  endRegion: GlobeRegion;
}

/** Zoom out, orbit around the globe, then ease in — no straight line through the core. */
export default function RegionViewCamera({
  region,
  disabled,
  earthRef,
  onTransitionChange,
}: {
  region: GlobeRegion;
  disabled: boolean;
  /** Kept for API symmetry with other globe cameras; region moves are camera-only. */
  earthRef: RefObject<Mesh | null>;
  onTransitionChange?: (active: boolean) => void;
}) {
  void earthRef;
  const { camera } = useThree();
  const controls = useThree((state) => state.controls as OrbitControlsImpl | null);
  const transition = useRef<Transition | null>(null);
  const endDirection = useRef(new Vector3());
  const endPosition = useRef(new Vector3());
  const lastRegionId = useRef(region.id);
  const transitionActiveRef = useRef(false);

  const setTransitionActive = (active: boolean) => {
    if (transitionActiveRef.current === active) {
      return;
    }
    transitionActiveRef.current = active;
    onTransitionChange?.(active);
  };

  useEffect(() => {
    if (lastRegionId.current === region.id) {
      return;
    }
    lastRegionId.current = region.id;

    const startDirection = camera.position.clone().normalize();
    viewDirection(region, endDirection.current);
    transition.current = {
      startedAt: performance.now(),
      startDistance: camera.position.length(),
      startDirection,
      endDirection: endDirection.current.clone(),
      endDistance: region.distance,
      endRegion: region,
    };
    setTransitionActive(true);
  }, [region, camera]);

  useFrame((_, delta) => {
    if (disabled) {
      return;
    }

    viewDirection(region, endDirection.current);
    cameraPosition(region, endDirection.current, region.distance, endPosition.current);

    const active = transition.current;
    const transitioning = active !== null;

    if (controls) {
      controls.enabled = !transitioning;
    }
    setTransitionActive(transitioning);

    if (!active) {
      const settle = 1 - Math.exp(-4 * Math.min(delta, 0.05));
      camera.position.lerp(endPosition.current, settle);
      camera.lookAt(0, 0, 0);
      return;
    }

    const elapsed = performance.now() - active.startedAt;
    const u = Math.min(1, elapsed / TRANSITION_MS);
    const distance = transitionDistance(u, active.startDistance, active.endDistance);
    const directionT = transitionDirectionT(u);

    slerpDirection(active.startDirection, active.endDirection, directionT, scratchDir);
    cameraPosition(active.endRegion, scratchDir, distance, camera.position);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    if (u >= 1) {
      transition.current = null;
      camera.position.copy(endPosition.current);
      camera.lookAt(0, 0, 0);
      if (controls) {
        controls.target.set(0, 0, 0);
        controls.update();
      }
    }
  });

  return null;
}
