"use client";

import { Html, useCursor } from "@react-three/drei";
import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import {
  DoubleSide,
  type Group,
  MathUtils,
  type MeshBasicMaterial,
  Quaternion,
  Vector3,
} from "three";
import RiskBadge from "@/components/risk-badge";
import { formatElevation, refreshLabel } from "@/lib/format";
import { RISK_COLORS } from "@/lib/theme";
import type { Mountain } from "@/lib/types";
import { latLonToVector3 } from "./geo";

const Z_AXIS = new Vector3(0, 0, 1);

/** Radius of the invisible sphere that catches the pointer. Larger than the dot on purpose. */
const HIT_RADIUS = 0.045;

/** Pixels the pointer may move between press and release and still count as a click, not a drag. */
const CLICK_TOLERANCE_PX = 5;

/** Ring opacity at rest and while hovered, before the horizon fade. */
const RING_OPACITY = 0.6;
const RING_OPACITY_HOVERED = 0.95;
const LIVE_RING_OPACITY = 0.35;

/**
 * Horizon fade: how squarely the marker faces the camera (1 = straight on, 0 = on the
 * horizon). Markers fade out across this range so none floats past the globe's edge.
 */
const FADE_START = 0.2;
const FADE_END = 0.03;

// Scratch vectors for the per-frame horizon check.
const worldPosition = new Vector3();
const outward = new Vector3();
const toCamera = new Vector3();

/**
 * One mountain on the globe: a dot and a halo in its risk color, lying flat on the
 * surface. Render it inside the rotating Earth mesh so it turns with the planet.
 */
export default function MountainMarker({
  mountain,
  radius,
  hovered,
  onHoverChange,
  onSelect,
}: {
  mountain: Mountain;
  radius: number;
  hovered: boolean;
  onHoverChange: (slug: string | null) => void;
  onSelect: (mountain: Mountain) => void;
}) {
  const color = RISK_COLORS[mountain.current_risk_level];
  const groupRef = useRef<Group>(null);
  const dotMaterial = useRef<MeshBasicMaterial>(null);
  const ringMaterial = useRef<MeshBasicMaterial>(null);
  const liveRingMaterial = useRef<MeshBasicMaterial>(null);
  const facingCamera = useRef(false);
  useCursor(hovered);

  // Local +Z points away from the globe's center, so rings lie flat on the surface.
  const { position, quaternion } = useMemo(() => {
    const normal = latLonToVector3(mountain.lat, mountain.lon).normalize();
    return {
      position: normal.clone().multiplyScalar(radius),
      quaternion: new Quaternion().setFromUnitVectors(Z_AXIS, normal),
    };
  }, [mountain.lat, mountain.lon, radius]);

  useFrame(({ camera }) => {
    const group = groupRef.current;
    if (!group) {
      return;
    }
    group.getWorldPosition(worldPosition);
    outward.copy(worldPosition).normalize();
    toCamera.copy(camera.position).sub(worldPosition).normalize();
    const fade = MathUtils.smoothstep(outward.dot(toCamera), FADE_END, FADE_START);

    facingCamera.current = fade > 0.5;
    group.visible = fade > 0.01;
    if (dotMaterial.current) dotMaterial.current.opacity = fade;
    if (ringMaterial.current) {
      ringMaterial.current.opacity = (hovered ? RING_OPACITY_HOVERED : RING_OPACITY) * fade;
    }
    if (liveRingMaterial.current) liveRingMaterial.current.opacity = LIVE_RING_OPACITY * fade;
  });

  // Runs on pointer over and on every move, so a marker that turns to face the camera
  // under a resting pointer still becomes hovered.
  function handlePointer(event: ThreeEvent<PointerEvent>) {
    if (!facingCamera.current) {
      return;
    }
    event.stopPropagation();
    if (!hovered) {
      onHoverChange(mountain.slug);
    }
  }

  function handleOut() {
    onHoverChange(null);
  }

  function handleClick(event: ThreeEvent<MouseEvent>) {
    if (!facingCamera.current || event.delta > CLICK_TOLERANCE_PX) {
      return;
    }
    event.stopPropagation();
    onSelect(mountain);
  }

  return (
    <group ref={groupRef} position={position} quaternion={quaternion} scale={hovered ? 1.35 : 1}>
      <mesh position={[0, 0, 0.006]}>
        <sphereGeometry args={[0.011, 20, 20]} />
        <meshBasicMaterial ref={dotMaterial} color={color} transparent opacity={0} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0, 0.002]}>
        <ringGeometry args={[0.018, 0.023, 48]} />
        <meshBasicMaterial
          ref={ringMaterial}
          color={color}
          transparent
          opacity={0}
          side={DoubleSide}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      {mountain.is_live && (
        <mesh position={[0, 0, 0.002]}>
          <ringGeometry args={[0.03, 0.032, 64]} />
          <meshBasicMaterial
            ref={liveRingMaterial}
            color={color}
            transparent
            opacity={0}
            side={DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}
      <mesh
        visible={false}
        onPointerOver={handlePointer}
        onPointerMove={handlePointer}
        onPointerOut={handleOut}
        onClick={handleClick}
      >
        <sphereGeometry args={[HIT_RADIUS, 12, 12]} />
      </mesh>
      {hovered && (
        // drei applies its pointerEvents prop only in transform mode. The wrapper class
        // keeps the card from catching the click meant for the marker under it.
        <Html zIndexRange={[20, 0]} wrapperClass="pointer-events-none">
          <MarkerCard mountain={mountain} />
        </Html>
      )}
    </group>
  );
}

/** Hover card: name, elevation, region, risk, and last refresh. */
function MarkerCard({ mountain }: { mountain: Mountain }) {
  return (
    <div className="w-64 translate-x-5 -translate-y-1/2 rounded-md border border-border bg-popover/95 px-3.5 py-3 shadow-xl shadow-black/40 backdrop-blur-sm">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{mountain.name}</p>
        <p className="font-mono text-xs text-muted-foreground">{formatElevation(mountain.elevation_m)}</p>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{mountain.region}</p>
      <RiskBadge level={mountain.current_risk_level} className="mt-2.5 text-xs text-foreground" />
      <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">{refreshLabel(mountain)}</p>
    </div>
  );
}
