"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { type RefObject, useEffect, useRef } from "react";
import { MathUtils, type Mesh, Quaternion, Vector3 } from "three";
import type { Mountain } from "@/lib/types";
import { latLonToVector3 } from "./geo";
import { FLY_DURATION_MS } from "./motion";

/** Camera distance from the globe's center when the flight ends. The surface is at 1. */
const END_DISTANCE = 1.45;

/** Extra distance at mid-flight for a half-turn hop, so long flights arc outward. */
const ARC_HEIGHT = 0.35;

interface Flight {
  mountain: Mountain;
  from: Vector3;
  turn: Quaternion;
  angle: number;
  fromDistance: number;
  duration: number;
  startedAt: number;
}

// Scratch objects for the per-frame camera update.
const partialTurn = new Quaternion();
const direction = new Vector3();

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/**
 * Moves the camera to face `target` in one continuous motion, then calls `onArrive`.
 * Keep the globe still and the orbit controls disabled while `target` is set.
 */
export default function CameraFlight({
  target,
  earth,
  onArrive,
}: {
  target: Mountain | null;
  earth: RefObject<Mesh | null>;
  onArrive: (mountain: Mountain) => void;
}) {
  const camera = useThree((state) => state.camera);
  const flight = useRef<Flight | null>(null);

  useEffect(() => {
    if (!target || !earth.current) {
      flight.current = null;
      return;
    }
    earth.current.updateWorldMatrix(true, false);
    const destination = earth.current
      .localToWorld(latLonToVector3(target.lat, target.lon))
      .normalize();
    const from = camera.position.clone().normalize();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    flight.current = {
      mountain: target,
      from,
      turn: new Quaternion().setFromUnitVectors(from, destination),
      angle: from.angleTo(destination),
      fromDistance: camera.position.length(),
      duration: reducedMotion ? 0 : FLY_DURATION_MS,
      startedAt: performance.now(),
    };
  }, [target, earth, camera]);

  useFrame(() => {
    const current = flight.current;
    if (!current) {
      return;
    }
    const t = current.duration
      ? Math.min(1, (performance.now() - current.startedAt) / current.duration)
      : 1;
    const eased = easeInOutCubic(t);
    const arc = Math.sin(Math.PI * t) * ARC_HEIGHT * (current.angle / Math.PI);

    partialTurn.identity().slerp(current.turn, eased);
    direction.copy(current.from).applyQuaternion(partialTurn);
    camera.position
      .copy(direction)
      .multiplyScalar(MathUtils.lerp(current.fromDistance, END_DISTANCE, eased) + arc);
    camera.lookAt(0, 0, 0);

    if (t >= 1) {
      flight.current = null;
      onArrive(current.mountain);
    }
  });

  return null;
}
