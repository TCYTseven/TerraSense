"use client";

import { useFrame } from "@react-three/fiber";
import { type RefObject, useRef } from "react";
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
  arrived: boolean;
}

// Scratch objects for the per-frame camera update.
const partialTurn = new Quaternion();
const direction = new Vector3();

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/** Plans a flight from the camera's current position to face the mountain on the globe. */
function planFlight(mountain: Mountain, earth: Mesh, cameraPosition: Vector3): Flight {
  earth.updateWorldMatrix(true, false);
  const destination = earth.localToWorld(latLonToVector3(mountain.lat, mountain.lon)).normalize();
  const from = cameraPosition.clone().normalize();
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return {
    mountain,
    from,
    turn: new Quaternion().setFromUnitVectors(from, destination),
    angle: from.angleTo(destination),
    fromDistance: cameraPosition.length(),
    duration: reducedMotion ? 0 : FLY_DURATION_MS,
    startedAt: performance.now(),
    arrived: false,
  };
}

/**
 * Moves the camera to face `target` in one continuous motion, then calls `onArrive` once.
 * The flight starts on the first frame where both `target` and the Earth mesh exist.
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
  const flight = useRef<Flight | null>(null);

  useFrame(({ camera }) => {
    if (!target) {
      flight.current = null;
      return;
    }
    let current = flight.current;
    if (!current || current.mountain !== target) {
      if (!earth.current) {
        return;
      }
      current = flight.current = planFlight(target, earth.current, camera.position);
    }
    if (current.arrived) {
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
      current.arrived = true;
      onArrive(current.mountain);
    }
  });

  return null;
}
