"use client";

import { Billboard, Html, useCursor } from "@react-three/drei";
import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import {
  DoubleSide,
  type Group,
  MathUtils,
  type MeshBasicMaterial,
  Quaternion,
  Shape,
  ShapeGeometry,
  Vector3,
} from "three";
import RiskBadge from "@/components/risk-badge";
import { displayRiskLevel, formatElevation, modelPredictionLabel, refreshLabel } from "@/lib/format";
import { RISK_COLORS, THEME } from "@/lib/theme";
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

/**
 * Zoom scaling: at or beyond this camera-to-marker distance (the default view is about 2.4)
 * a marker draws at full size. Closer in, it shrinks in proportion, so it keeps a steady
 * size on screen while the gaps between neighboring peaks open up as you zoom.
 */
const FULL_SIZE_DISTANCE = 2.4;
const MIN_ZOOM_SCALE = 0.2;

/** Extra scale on the hovered marker. */
const HOVER_SCALE = 1.35;

/** Height of the mountain glyph, in globe radii. */
const GLYPH_SIZE = 0.05;

/** Radius of the glow sphere behind the glyph for dangerous mountains (high and extreme). */
const DANGER_SPHERE_RADIUS = { high: 0.046, extreme: 0.056 } as const;
const DANGER_SPHERE_OPACITY = 0.4;

function shape(points: [number, number][]): Shape {
  const s = new Shape();
  points.forEach(([x, y], i) => (i === 0 ? s.moveTo(x, y) : s.lineTo(x, y)));
  s.closePath();
  return s;
}

// The mountain glyph in a unit box, base on y = 0: a lower left peak and a taller right peak.
const PEAKS: [number, number][] = [[-0.62, 0], [-0.28, 0.58], [-0.1, 0.36], [0.2, 0.9], [0.62, 0]];
// The snowcap on the tall peak, with a jagged lower edge.
const SNOW: [number, number][] = [[0.2, 0.9], [0.37, 0.6], [0.28, 0.66], [0.2, 0.58], [0.12, 0.66], [0.04, 0.62]];
// The outline: the same peaks grown a little, drawn behind in the dark background color.
const OUTLINE: [number, number][] = [[-0.74, -0.06], [-0.28, 0.7], [-0.1, 0.5], [0.2, 1.04], [0.74, -0.06]];

const PEAKS_GEOMETRY = new ShapeGeometry(shape(PEAKS));
const SNOW_GEOMETRY = new ShapeGeometry(shape(SNOW));
const OUTLINE_GEOMETRY = new ShapeGeometry(shape(OUTLINE));

/** Visual meshes skip raycasting, so the pointer always reaches the hit sphere. */
const noRaycast = () => null;

// Scratch vectors for the per-frame horizon check.
const worldPosition = new Vector3();
const outward = new Vector3();
const toCamera = new Vector3();

/**
 * One mountain on the globe: a mountain glyph in its risk color that always faces the camera,
 * standing on a halo ring that lies flat on the surface. Dangerous mountains (high and extreme)
 * also get a translucent sphere in their risk color, centered on the glyph. Render it inside
 * the rotating Earth mesh so it turns with the planet.
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
  const level = displayRiskLevel(mountain);
  const color = RISK_COLORS[level];
  const groupRef = useRef<Group>(null);
  const glyphMaterial = useRef<MeshBasicMaterial>(null);
  const snowMaterial = useRef<MeshBasicMaterial>(null);
  const outlineMaterial = useRef<MeshBasicMaterial>(null);
  const sphereMaterial = useRef<MeshBasicMaterial>(null);
  const dangerRadius = level === "high" || level === "extreme" ? DANGER_SPHERE_RADIUS[level] : null;
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
    const zoomScale = MathUtils.clamp(
      camera.position.distanceTo(worldPosition) / FULL_SIZE_DISTANCE,
      MIN_ZOOM_SCALE,
      1,
    );
    group.scale.setScalar(zoomScale * (hovered ? HOVER_SCALE : 1));

    facingCamera.current = fade > 0.5;
    group.visible = fade > 0.01;
    for (const material of [glyphMaterial, snowMaterial, outlineMaterial]) {
      if (material.current) material.current.opacity = fade;
    }
    if (sphereMaterial.current) sphereMaterial.current.opacity = DANGER_SPHERE_OPACITY * fade;
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
    <group ref={groupRef} position={position} quaternion={quaternion}>
      {dangerRadius && (
        <mesh position={[0, 0, 0.004]} raycast={noRaycast}>
          <sphereGeometry args={[dangerRadius, 32, 32]} />
          <meshBasicMaterial
            ref={sphereMaterial}
            color={color}
            transparent
            opacity={0}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}
      <Billboard position={[0, 0, 0.004]}>
        {/* Centered on the mountain's point, so the glyph sits in the middle of its sphere. */}
        <group scale={GLYPH_SIZE} position={[0, -GLYPH_SIZE * 0.47, 0]}>
          <mesh geometry={OUTLINE_GEOMETRY} renderOrder={1} raycast={noRaycast}>
            <meshBasicMaterial
              ref={outlineMaterial}
              color={THEME.background}
              transparent
              opacity={0}
              depthTest={false}
              toneMapped={false}
            />
          </mesh>
          <mesh geometry={PEAKS_GEOMETRY} renderOrder={2} raycast={noRaycast}>
            <meshBasicMaterial ref={glyphMaterial} color={color} transparent opacity={0} depthTest={false} toneMapped={false} />
          </mesh>
          <mesh geometry={SNOW_GEOMETRY} renderOrder={3} raycast={noRaycast}>
            <meshBasicMaterial ref={snowMaterial} color="#ffffff" transparent opacity={0} depthTest={false} toneMapped={false} />
          </mesh>
        </group>
      </Billboard>
      <mesh position={[0, 0, 0.002]} raycast={noRaycast}>
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
        <mesh position={[0, 0, 0.002]} raycast={noRaycast}>
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

/** Hover card: name, elevation, region, risk, the model's prediction, and last refresh. */
function MarkerCard({ mountain }: { mountain: Mountain }) {
  const modelLine = modelPredictionLabel(mountain);
  return (
    <div className="w-64 translate-x-5 -translate-y-1/2 rounded-md border border-border bg-popover/95 px-3.5 py-3 shadow-xl shadow-foreground/10 backdrop-blur-sm">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{mountain.name}</p>
        <p className="font-mono text-xs text-muted-foreground">{formatElevation(mountain.elevation_m)}</p>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{mountain.region}</p>
      <RiskBadge level={displayRiskLevel(mountain)} className="mt-2.5 text-xs text-foreground" />
      {modelLine && <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">{modelLine}</p>}
      <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">{refreshLabel(mountain)}</p>
    </div>
  );
}
