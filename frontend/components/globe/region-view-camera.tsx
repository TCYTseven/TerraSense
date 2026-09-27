"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { type RefObject, useEffect, useRef } from "react";
import { type Mesh, Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { GlobeRegion } from "@/lib/globe-regions";
import { latLonToVector3 } from "./geo";

const TRANSITION_MS = 2600;
/** Extra camera distance at mid-move, on top of the start→end lerp, so the pull-back overlaps the turn. */
const ARC = 0.9;

const scratchLocal = new Vector3();
const scratchWorld = new Vector3();
const scratchStartDir = new Vector3();
const scratchEndDir = new Vector3();

function smootherStep(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x * x * x * (x * (x * 6 - 15) + 10);
}

function lerpAngle(from: number, to: number, t: number): number {
  const delta = Math.atan2(Math.sin(to - from), Math.cos(to - from));
  return from + delta * t;
}

/** World-space direction of a lat/lon after a given earth Y spin. Restores the mesh rotation. */
function worldDirectionAtY(earth: Mesh, lat: number, lon: number, rotationY: number, out: Vector3): Vector3 {
  const savedY = earth.rotation.y;
  earth.rotation.y = rotationY;
  earth.updateWorldMatrix(true, false);
  scratchLocal.copy(latLonToVector3(lat, lon, 1));
  out.copy(earth.localToWorld(scratchLocal)).normalize();
  earth.rotation.y = savedY;
  earth.updateWorldMatrix(true, false);
  return out;
}

/**
 * Y spin that brings (lat, lon) as close as possible to `face`, using a fresh local point each sample.
 * Axial tilt means Y spin alone cannot hit every latitude, so the camera finishes on the point itself.
 */
function targetEarthRotationY(earth: Mesh, lat: number, lon: number, face: Vector3): number {
  const savedY = earth.rotation.y;
  const local = latLonToVector3(lat, lon, 1);
  let bestY = savedY;
  let bestDot = -Infinity;
  const steps = 720;
  for (let i = 0; i <= steps; i += 1) {
    earth.rotation.y = (i / steps) * Math.PI * 2;
    earth.updateWorldMatrix(true, false);
    scratchLocal.copy(local);
    scratchWorld.copy(earth.localToWorld(scratchLocal)).normalize();
    const dot = scratchWorld.dot(face);
    if (dot > bestDot) {
      bestDot = dot;
      bestY = earth.rotation.y;
    }
  }
  earth.rotation.y = savedY;
  earth.updateWorldMatrix(true, false);
  return bestY;
}

/** One curve: zoom and turn share the same t. A sine arc pulls the camera out while the globe turns. */
function transitionDistance(t: number, startDistance: number, endDistance: number): number {
  const base = startDistance + (endDistance - startDistance) * t;
  return base + Math.sin(Math.PI * t) * ARC;
}

interface Transition {
  startedAt: number;
  startCamera: Vector3;
  endCamera: Vector3;
  startEarthY: number;
  endEarthY: number;
}

/** Pull the camera out and turn the globe in the same motion, then settle on the region. */
export default function RegionViewCamera({
  region,
  disabled,
  earthRef,
  onTransitionChange,
}: {
  region: GlobeRegion;
  disabled: boolean;
  earthRef: RefObject<Mesh | null>;
  onTransitionChange?: (active: boolean) => void;
}) {
  const { camera } = useThree();
  const controls = useThree((state) => state.controls as OrbitControlsImpl | null);
  const transition = useRef<Transition | null>(null);
  const lastRegionId = useRef(region.id);
  const transitionActiveRef = useRef(false);
  const heldEarthY = useRef<number | null>(null);

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

    const earth = earthRef.current;
    const startDir = camera.position.clone().normalize();
    const startEarthY = earth?.rotation.y ?? 0;
    let endEarthY = startEarthY;
    const endDir = startDir.clone();
    if (earth && region.id !== "world") {
      endEarthY = targetEarthRotationY(earth, region.lat, region.lon, startDir);
      worldDirectionAtY(earth, region.lat, region.lon, endEarthY, endDir);
    }

    const endCam = endDir.multiplyScalar(region.distance);
    transition.current = {
      startedAt: performance.now(),
      startCamera: camera.position.clone(),
      endCamera: endCam,
      startEarthY,
      endEarthY,
    };
    heldEarthY.current = null;
    setTransitionActive(true);
  }, [region, camera, earthRef]);

  useFrame(() => {
    if (disabled) {
      return;
    }

    const earth = earthRef.current;
    const active = transition.current;
    const transitioning = active !== null;

    if (controls) {
      controls.enabled = !transitioning;
    }
    setTransitionActive(transitioning);

    if (active && earth) {
      const elapsed = performance.now() - active.startedAt;
      const u = Math.min(1, elapsed / TRANSITION_MS);
      const moveT = smootherStep(u);
      const dist = transitionDistance(moveT, active.startCamera.length(), active.endCamera.length());

      earth.rotation.y = lerpAngle(active.startEarthY, active.endEarthY, moveT);

      scratchStartDir.copy(active.startCamera).normalize();
      scratchEndDir.copy(active.endCamera).normalize();
      scratchWorld.copy(scratchStartDir).lerp(scratchEndDir, moveT).normalize();
      camera.position.copy(scratchWorld).multiplyScalar(dist);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();

      if (u >= 1) {
        transition.current = null;
        earth.rotation.y = active.endEarthY;
        heldEarthY.current = active.endEarthY;
        camera.position.copy(active.endCamera);
        camera.lookAt(0, 0, 0);
        if (controls) {
          controls.target.set(0, 0, 0);
          controls.update();
        }
      }
      return;
    }

    if (!active && region.id !== "world" && heldEarthY.current !== null && earth) {
      earth.rotation.y = heldEarthY.current;
    }

    if (!active && region.id === "world") {
      heldEarthY.current = null;
    }
  });

  return null;
}
