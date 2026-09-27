"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { type RefObject, useEffect, useRef } from "react";
import { type Mesh, Quaternion, Vector3 } from "three";
import type { GlobeRegion } from "@/lib/globe-regions";
import { latLonToVector3 } from "./geo";

/** Pull back outside the normal zoom band so the camera arcs around the hull, not through it. */
const RETREAT_DISTANCE = 4.35;
const TRANSITION_MS = 2400;
const RETREAT_FRAC = 0.28;
const ORBIT_FRAC = 0.44;
const APPROACH_FRAC = 0.28;

const scratchDir = new Vector3();
const scratchQuat = new Quaternion();
const scratchStartQuat = new Quaternion();
const scratchEndQuat = new Quaternion();
const scratchAxis = new Vector3(0, 0, 1);

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
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
  scratchQuat.copy(scratchStartQuat).slerp(scratchEndQuat, t);
  return out.copy(scratchAxis).applyQuaternion(scratchQuat).normalize();
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
}: {
  region: GlobeRegion;
  disabled: boolean;
  earthRef: RefObject<Mesh | null>;
}) {
  const { camera } = useThree();
  const transition = useRef<Transition | null>(null);
  const endDirection = useRef(new Vector3());
  const endPosition = useRef(new Vector3());
  const lastRegionId = useRef(region.id);

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
  }, [region, camera]);

  useFrame((_, delta) => {
    if (disabled) {
      return;
    }

    viewDirection(region, endDirection.current);
    cameraPosition(region, endDirection.current, region.distance, endPosition.current);

    const active = transition.current;
    if (!active) {
      const settle = 1 - Math.exp(-5 * Math.min(delta, 0.05));
      camera.position.lerp(endPosition.current, settle);
      camera.lookAt(0, 0, 0);
      return;
    }

    const elapsed = performance.now() - active.startedAt;
    const u = Math.min(1, elapsed / TRANSITION_MS);
    const retreatEnd = RETREAT_FRAC;
    const orbitEnd = RETREAT_FRAC + ORBIT_FRAC;

    let distance: number;
    let directionT: number;
    let spinBoost = 0;

    if (u <= retreatEnd) {
      const t = easeInOutCubic(u / retreatEnd);
      distance = active.startDistance + (RETREAT_DISTANCE - active.startDistance) * t;
      directionT = 0;
    } else if (u <= orbitEnd) {
      const t = easeInOutCubic((u - retreatEnd) / ORBIT_FRAC);
      distance = RETREAT_DISTANCE;
      directionT = t;
      spinBoost = delta * 0.55;
    } else {
      const t = easeInOutCubic((u - orbitEnd) / APPROACH_FRAC);
      distance = RETREAT_DISTANCE + (active.endDistance - RETREAT_DISTANCE) * t;
      directionT = 1;
    }

    slerpDirection(active.startDirection, active.endDirection, directionT, scratchDir);
    cameraPosition(active.endRegion, scratchDir, distance, camera.position);

    if (earthRef.current && spinBoost > 0) {
      earthRef.current.rotation.y += spinBoost;
    }

    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    if (u >= 1) {
      transition.current = null;
    }
  });

  return null;
}
