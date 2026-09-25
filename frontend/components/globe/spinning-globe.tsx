"use client";

import { OrbitControls, useTexture } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame } from "@react-three/fiber";
import { type ReactNode, type RefObject, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  AdditiveBlending,
  BackSide,
  Color,
  type Mesh,
  ShaderMaterial,
  SRGBColorSpace,
} from "three";
import { THEME } from "@/lib/theme";
import type { Mountain } from "@/lib/types";
import CameraFlight from "./camera-flight";
import MountainMarker from "./mountain-marker";

/** Radians per second. One full turn takes about 100 seconds. */
const IDLE_SPIN_RADIANS_PER_SECOND = 0.06;

/** Earth's axial tilt, in radians. */
const AXIAL_TILT_RADIANS = 0.41;

const EARTH_RADIUS = 1;

const ATMOSPHERE_VERTEX_SHADER = /* glsl */ `
  varying vec3 vNormal;

  void main() {
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const ATMOSPHERE_FRAGMENT_SHADER = /* glsl */ `
  uniform vec3 glowColor;
  varying vec3 vNormal;

  void main() {
    float intensity = pow(0.62 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.4);
    gl_FragColor = vec4(glowColor, 1.0) * intensity;
  }
`;

/** Stops a pointer event here, so markers on the far side of the globe cannot be hovered or clicked. */
function blockPointer(event: ThreeEvent<PointerEvent> | ThreeEvent<MouseEvent>) {
  event.stopPropagation();
}

/**
 * Satellite Earth that rotates on its axis. Children ride on the surface and turn with it.
 */
function Earth({
  meshRef,
  spinning,
  onReady,
  children,
}: {
  meshRef: RefObject<Mesh | null>;
  spinning: boolean;
  onReady: () => void;
  children?: ReactNode;
}) {
  const [colorMap, bumpMap] = useTexture(
    ["/globe/earth-day.jpg", "/globe/earth-topology.png"],
    (textures) => {
      const [dayMap] = textures;
      dayMap.colorSpace = SRGBColorSpace;
      dayMap.anisotropy = 8;
    },
  );

  // Earth suspends until its textures load, so this runs once the globe is on screen.
  useEffect(() => {
    onReady();
  }, [onReady]);

  useFrame((_, delta) => {
    if (!meshRef.current || !spinning) {
      return;
    }

    const step = Math.min(delta, 0.05);
    meshRef.current.rotation.y += step * IDLE_SPIN_RADIANS_PER_SECOND;
  });

  return (
    <group rotation={[0, 0, AXIAL_TILT_RADIANS]}>
      <mesh
        ref={meshRef}
        onPointerOver={blockPointer}
        onPointerMove={blockPointer}
        onClick={blockPointer}
      >
        <sphereGeometry args={[EARTH_RADIUS, 96, 96]} />
        <meshStandardMaterial
          map={colorMap}
          bumpMap={bumpMap}
          bumpScale={0.035}
          roughness={0.9}
          metalness={0.02}
        />
        {children}
      </mesh>
    </group>
  );
}

/**
 * Thin atmospheric rim that stays fixed while the surface turns.
 */
function Atmosphere() {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: {
          glowColor: { value: new Color("#9fd4ff") },
        },
        vertexShader: ATMOSPHERE_VERTEX_SHADER,
        fragmentShader: ATMOSPHERE_FRAGMENT_SHADER,
        blending: AdditiveBlending,
        side: BackSide,
        transparent: true,
        depthWrite: false,
      }),
    [],
  );

  useEffect(() => {
    return () => {
      material.dispose();
    };
  }, [material]);

  return (
    <mesh scale={1.12}>
      <sphereGeometry args={[EARTH_RADIUS, 64, 64]} />
      <primitive object={material} attach="material" />
    </mesh>
  );
}

/**
 * Full-viewport globe with one marker per mountain. Drag to orbit and scroll to zoom.
 * The surface keeps turning, except while a marker is hovered or the camera is flying.
 * Clicking a marker calls onSelect. Set flyTarget to fly there; onArrive fires on landing.
 * onReady fires once the textured globe is on screen.
 */
export default function SpinningGlobe({
  mountains,
  flyTarget,
  onSelect,
  onArrive,
  onReady,
}: {
  mountains: Mountain[];
  flyTarget: Mountain | null;
  onSelect: (mountain: Mountain) => void;
  onArrive: (mountain: Mountain) => void;
  onReady: () => void;
}) {
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null);
  const earthRef = useRef<Mesh>(null);
  const flying = flyTarget !== null;

  return (
    <Canvas
      camera={{ position: [0, 0.25, 3.4], fov: 40 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: false }}
    >
      <color attach="background" args={[THEME.background]} />
      <ambientLight intensity={0.22} />
      <directionalLight position={[4.5, 1.6, 3.2]} intensity={2.1} color="#fff4e5" />
      <directionalLight position={[-3.5, -1.2, -2]} intensity={0.18} color="#6f93b5" />
      <Suspense fallback={null}>
        <Earth meshRef={earthRef} spinning={hoveredSlug === null && !flying} onReady={onReady}>
          {mountains.map((mountain) => (
            <MountainMarker
              key={mountain.slug}
              mountain={mountain}
              radius={EARTH_RADIUS}
              hovered={!flying && hoveredSlug === mountain.slug}
              onHoverChange={setHoveredSlug}
              onSelect={onSelect}
            />
          ))}
        </Earth>
      </Suspense>
      <CameraFlight target={flyTarget} earth={earthRef} onArrive={onArrive} />
      <Atmosphere />
      <OrbitControls
        enabled={!flying}
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        rotateSpeed={0.45}
        minDistance={1.7}
        maxDistance={5}
      />
    </Canvas>
  );
}
