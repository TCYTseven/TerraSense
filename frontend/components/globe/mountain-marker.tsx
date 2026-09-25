"use client";

import { Html, useCursor } from "@react-three/drei";
import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import {
  DataTexture,
  DoubleSide,
  type Group,
  LinearFilter,
  type Material,
  MathUtils,
  type Mesh,
  Quaternion,
  Vector3,
} from "three";
import RiskBadge from "@/components/risk-badge";
import { formatElevation, refreshLabel } from "@/lib/format";
import { GLOBE_COLORS, RISK_COLORS } from "@/lib/theme";
import type { Mountain } from "@/lib/types";
import { latLonToVector3 } from "./geo";
import { KEY_LIGHT_DIRECTION } from "./lighting";

const Z_AXIS = new Vector3(0, 0, 1);

/** Peak size in globe radii. Tall enough to read as a mountain at the default zoom. */
const PEAK_HEIGHT = 0.066;
const PEAK_RADIUS = 0.032;
/** Few sides and flat shading, so the lit and shaded faces read as a low-poly peak. */
const PEAK_SIDES = 5;
/** Share of the peak's height, from the top, that is snow. */
const SNOW_SHARE = 0.38;
const SNOW_HEIGHT = PEAK_HEIGHT * SNOW_SHARE;
/** Lifts the snow cap off the peak's faces so the two never z-fight. */
const SNOW_LIFT = 0.0015;
/** three.js cones point up +Y. This turns them to the marker's +Z, away from the globe. */
const CONE_TO_UP: [number, number, number] = [Math.PI / 2, 0, 0];
/**
 * The peak grows from its base while hovered, but only as far as it can without its tip
 * reaching the horizon fade. Near the globe's edge it grows less, and stays clickable.
 */
const HOVER_SCALE = 1.35;

/**
 * Facet shading, baked into a matcap: the key light's side is bright, a weak fill from the
 * lower right keeps the shaded faces apart, and faces turned away from the viewer darken a
 * little. The floor is the darkest a face gets: low on the rock so the peak reads as a
 * solid on a bright globe, higher on the snow so shaded snow stays light.
 */
const PEAK_SHADE_FLOOR = 0.36;
const SNOW_SHADE_FLOOR = 0.62;
const FILL_LIGHT_DIRECTION = new Vector3(0.8, -0.6, 0.9).normalize();

/** Soft shadow under the peak, and the thin ring that marks a live mountain. */
const SHADOW_RADIUS = 0.058;
const SHADOW_OPACITY = 0.3;
const LIVE_RING_RADII = [0.048, 0.053] as const;
const LIVE_RING_OPACITY = 0.95;

/** Radius of the invisible sphere that catches the pointer, centered halfway up the peak. */
const HIT_RADIUS = 0.052;

/** Pixels the pointer may move between press and release and still count as a click, not a drag. */
const CLICK_TOLERANCE_PX = 5;

/**
 * Horizon fade, part one: how squarely the marker's base faces the camera (1 = straight
 * on, 0 = on the horizon). Hides markers on the far side of the globe.
 */
const FADE_START = 0.2;
const FADE_END = 0.03;

/**
 * Horizon fade, part two: the peak stands up off the surface, so near the horizon its tip
 * would poke past the globe's silhouette before its base reaches the edge. The marker fades
 * out as the tip's line of sight closes on the edge (in globe radii), and is gone when the
 * tip would leave the disk.
 */
const TIP_FADE_MARGIN = 0.03;

// Draw order among the transparent marker parts: flat decals, then the peak, then its snow.
const DECAL_ORDER = 1;
const PEAK_ORDER = 2;
const SNOW_ORDER = 3;

// Scratch vectors for the per-frame horizon check.
const worldPosition = new Vector3();
const outward = new Vector3();
const toCamera = new Vector3();
const tip = new Vector3();
const sightLine = new Vector3();

let shadowAlphaMap: DataTexture | null = null;
const facetMatcaps = new Map<number, DataTexture>();

/**
 * A matcap (a lit sphere, looked up by each face's view-space normal) for flat-shaded
 * facets. It lights the peaks the same way whatever the scene lights do. Shared per floor.
 */
function getFacetMatcap(floor: number): DataTexture {
  const cached = facetMatcaps.get(floor);
  if (cached) {
    return cached;
  }
  const size = 64;
  const data = new Uint8Array(size * size * 4);
  const normal = new Vector3();
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      const x = ((col + 0.5) / size) * 2 - 1;
      const y = ((row + 0.5) / size) * 2 - 1;
      normal.set(x, y, Math.sqrt(Math.max(0, 1 - x * x - y * y)));
      const light =
        0.75 * Math.max(0, normal.dot(KEY_LIGHT_DIRECTION)) +
        0.25 * Math.max(0, normal.dot(FILL_LIGHT_DIRECTION)) +
        0.15 * normal.z;
      const shade = floor + (1 - floor) * Math.min(1, light);
      const i = (row * size + col) * 4;
      data[i] = data[i + 1] = data[i + 2] = Math.round(shade * 255);
      data[i + 3] = 255;
    }
  }
  const matcap = new DataTexture(data, size, size);
  matcap.magFilter = LinearFilter;
  matcap.minFilter = LinearFilter;
  matcap.needsUpdate = true;
  facetMatcaps.set(floor, matcap);
  return matcap;
}

/** A soft round falloff for the contact shadow, shared by every marker. */
function getShadowAlphaMap(): DataTexture {
  if (shadowAlphaMap) {
    return shadowAlphaMap;
  }
  const size = 64;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const distance = Math.hypot(((x + 0.5) / size) * 2 - 1, ((y + 0.5) / size) * 2 - 1);
      // Dense under and just around the peak's base, then a soft falloff.
      const alpha = 1 - MathUtils.smoothstep(distance, 0.45, 1);
      const i = (y * size + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = Math.round(alpha * 255);
      data[i + 3] = 255;
    }
  }
  shadowAlphaMap = new DataTexture(data, size, size);
  shadowAlphaMap.magFilter = LinearFilter;
  shadowAlphaMap.minFilter = LinearFilter;
  shadowAlphaMap.needsUpdate = true;
  return shadowAlphaMap;
}

/**
 * How far inside the globe's disk the tip of a peak this tall appears from the camera: the
 * line of sight's closest approach to the globe's center, subtracted from the radius.
 * Negative once the tip shows past the silhouette. Reads worldPosition and outward.
 */
function tipInset(height: number, cameraPosition: Vector3, radius: number): number {
  tip.copy(outward).multiplyScalar(height).add(worldPosition);
  sightLine.copy(tip).sub(cameraPosition).normalize();
  const along = -cameraPosition.dot(sightLine);
  const closest = sightLine.multiplyScalar(along).add(cameraPosition).length();
  return radius - closest;
}

/**
 * Scales every material in the marker by the horizon fade. Each material keeps its full
 * opacity in userData.opacity; the invisible hit sphere has none and is left alone.
 */
function fadeMaterials(group: Group, fade: number) {
  group.traverse((object) => {
    const material = (object as Mesh).material as Material | undefined;
    const full = material?.userData.opacity;
    if (material && typeof full === "number") {
      material.opacity = full * fade;
    }
  });
}

/**
 * One mountain on the globe: a small low-poly peak in its risk color with a snow cap,
 * standing on the surface along the local normal. A live mountain also gets a thin ring
 * at its base. Render it inside the rotating Earth mesh so it turns with the planet.
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
  const facingCamera = useRef(false);
  const shadowMap = useMemo(() => getShadowAlphaMap(), []);
  const peakMatcap = useMemo(() => getFacetMatcap(PEAK_SHADE_FLOOR), []);
  const snowMatcap = useMemo(() => getFacetMatcap(SNOW_SHADE_FLOOR), []);
  useCursor(hovered);

  // Local +Z points away from the globe's center, so the peak stands up and the decals lie flat.
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
    const facing = MathUtils.smoothstep(outward.dot(toCamera), FADE_END, FADE_START);
    const restInset = tipInset(PEAK_HEIGHT, camera.position, radius);
    const fade = Math.min(facing, MathUtils.smoothstep(restInset, 0, TIP_FADE_MARGIN));

    let scale = 1;
    if (hovered) {
      // Spend only the inset the resting tip has beyond the fade margin.
      const lost = restInset - tipInset(PEAK_HEIGHT * HOVER_SCALE, camera.position, radius);
      const room = restInset - TIP_FADE_MARGIN;
      scale = 1 + (HOVER_SCALE - 1) * (lost > 0 ? MathUtils.clamp(room / lost, 0, 1) : 1);
    }
    group.scale.setScalar(scale);

    facingCamera.current = fade > 0.5;
    group.visible = fade > 0.01;
    fadeMaterials(group, fade);
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
      <mesh position={[0, 0, 0.001]} renderOrder={DECAL_ORDER}>
        <circleGeometry args={[SHADOW_RADIUS, 32]} />
        <meshBasicMaterial
          color={GLOBE_COLORS.shadow}
          alphaMap={shadowMap}
          transparent
          opacity={0}
          userData={{ opacity: SHADOW_OPACITY }}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      {mountain.is_live && (
        <mesh position={[0, 0, 0.0015]} renderOrder={DECAL_ORDER}>
          <ringGeometry args={[LIVE_RING_RADII[0], LIVE_RING_RADII[1], 64]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0}
            userData={{ opacity: LIVE_RING_OPACITY }}
            side={DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}
      <mesh rotation={CONE_TO_UP} position={[0, 0, PEAK_HEIGHT / 2]} renderOrder={PEAK_ORDER}>
        <coneGeometry args={[PEAK_RADIUS, PEAK_HEIGHT, PEAK_SIDES]} />
        <meshMatcapMaterial
          color={color}
          matcap={peakMatcap}
          flatShading
          transparent
          opacity={0}
          userData={{ opacity: 1 }}
        />
      </mesh>
      {/* The snow cap: the top of the peak, open at the bottom, just proud of the peak's faces. */}
      <mesh
        rotation={CONE_TO_UP}
        position={[0, 0, PEAK_HEIGHT + SNOW_LIFT - SNOW_HEIGHT / 2]}
        renderOrder={SNOW_ORDER}
      >
        <coneGeometry args={[PEAK_RADIUS * SNOW_SHARE, SNOW_HEIGHT, PEAK_SIDES, 1, true]} />
        <meshMatcapMaterial
          color={GLOBE_COLORS.snow}
          matcap={snowMatcap}
          flatShading
          transparent
          opacity={0}
          userData={{ opacity: 1 }}
        />
      </mesh>
      <mesh
        visible={false}
        position={[0, 0, PEAK_HEIGHT / 2]}
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
        <Html position={[0, 0, PEAK_HEIGHT * 0.6]} zIndexRange={[20, 0]} wrapperClass="pointer-events-none">
          <MarkerCard mountain={mountain} />
        </Html>
      )}
    </group>
  );
}

/** Hover card: name, elevation, region, risk, and last refresh. */
function MarkerCard({ mountain }: { mountain: Mountain }) {
  return (
    <div className="w-64 translate-x-6 -translate-y-1/2 rounded-lg border border-border bg-popover px-3.5 py-3">
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
