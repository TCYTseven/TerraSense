"use client";

import { OrbitControls, useTexture } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame } from "@react-three/fiber";
import { type ReactNode, type RefObject, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Color,
  type DirectionalLight,
  type Mesh,
  NormalBlending,
  ShaderMaterial,
  SRGBColorSpace,
} from "three";
import { GLOBE_COLORS } from "@/lib/theme";
import type { Mountain } from "@/lib/types";
import CameraFlight from "./camera-flight";
import { KEY_LIGHT_DIRECTION } from "./lighting";
import MountainMarker from "./mountain-marker";

/** Radians per second. One full turn takes about 100 seconds. */
const IDLE_SPIN_RADIANS_PER_SECOND = 0.06;

/** Earth's axial tilt, in radians. */
const AXIAL_TILT_RADIANS = 0.41;

/**
 * The longitude that faces the camera on load: between Rainier and Huascarán, so both
 * peaks start well inside the globe's edge and the spin carries Rainier toward the center.
 * Turning the sphere by y radians brings longitude -90 - y (in degrees) to the front.
 */
const START_LONGITUDE = -105;
const START_ROTATION: [number, number, number] = [0, ((-90 - START_LONGITUDE) * Math.PI) / 180, 0];

const EARTH_RADIUS = 1;

/**
 * Lighting is even on purpose: no night side. The hemisphere light fills every face, and a
 * soft key light from the viewer's upper left gives the globe and the peaks their shape.
 * With tone mapping off, irradiance near pi shows the texture at its own colors.
 */
const HEMISPHERE_INTENSITY = 2.6;
const KEY_LIGHT_INTENSITY = 0.75;

/** How much the relief map tilts the surface's shading. */
const BUMP_SCALE = 0.02;

/** The atmosphere: a rim just past the edge of the globe that thins out over RIM_WIDTH. */
const RIM_WIDTH = 0.13;
const RIM_OPACITY = 0.5;
/** A thin haze on the globe itself, strongest at its edge. */
const HAZE_OPACITY = 0.3;
/** The shell that carries the rim. It must reach past EARTH_RADIUS + RIM_WIDTH. */
const ATMOSPHERE_SHELL_RADIUS = 1.2;

const ATMOSPHERE_VERTEX_SHADER = /* glsl */ `
  varying vec3 vWorldPosition;

  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorldPosition = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

// Each pixel's view ray passes the globe's center (the origin) at some closest distance.
// Past the surface that distance sets the rim's fade, so the rim hugs the silhouette at
// any zoom. On the globe it adds a thin haze that thickens toward the edge.
const ATMOSPHERE_FRAGMENT_SHADER = /* glsl */ `
  uniform vec3 rimColor;
  uniform float rimOpacity;
  uniform float rimWidth;
  uniform float hazeOpacity;
  uniform float earthRadius;
  varying vec3 vWorldPosition;

  void main() {
    vec3 ray = normalize(vWorldPosition - cameraPosition);
    float closest = length(cameraPosition - ray * dot(cameraPosition, ray));
    float alpha;
    if (closest > earthRadius) {
      float t = clamp((closest - earthRadius) / rimWidth, 0.0, 1.0);
      alpha = rimOpacity * pow(1.0 - t, 2.2);
    } else {
      alpha = hazeOpacity * pow(closest / earthRadius, 18.0);
    }
    gl_FragColor = vec4(rimColor, alpha);
    #include <colorspace_fragment>
  }
`;

/** Stops a pointer event here, so markers on the far side of the globe cannot be hovered or clicked. */
function blockPointer(event: ThreeEvent<PointerEvent> | ThreeEvent<MouseEvent>) {
  event.stopPropagation();
}

/** A soft directional light that stays at the viewer's upper left, so the lit side always faces the camera. */
function KeyLight() {
  const light = useRef<DirectionalLight>(null);

  useFrame(({ camera }) => {
    light.current?.position.copy(KEY_LIGHT_DIRECTION).applyQuaternion(camera.quaternion);
  });

  return <directionalLight ref={light} intensity={KEY_LIGHT_INTENSITY} color={GLOBE_COLORS.sun} />;
}

/**
 * Light atlas Earth that rotates on its axis. Children ride on the surface and turn with it.
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
    ["/globe/earth-light.jpg", "/globe/earth-topology.png"],
    (textures) => {
      const [atlasMap] = textures;
      atlasMap.colorSpace = SRGBColorSpace;
      atlasMap.anisotropy = 8;
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
        rotation={START_ROTATION}
        onPointerOver={blockPointer}
        onPointerMove={blockPointer}
        onClick={blockPointer}
      >
        <sphereGeometry args={[EARTH_RADIUS, 128, 96]} />
        <meshLambertMaterial map={colorMap} bumpMap={bumpMap} bumpScale={BUMP_SCALE} />
        {children}
      </mesh>
    </group>
  );
}

/**
 * Soft light-blue rim around the globe that stays fixed while the surface turns.
 */
function Atmosphere() {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: {
          rimColor: { value: new Color(GLOBE_COLORS.atmosphere) },
          rimOpacity: { value: RIM_OPACITY },
          rimWidth: { value: RIM_WIDTH },
          hazeOpacity: { value: HAZE_OPACITY },
          earthRadius: { value: EARTH_RADIUS },
        },
        vertexShader: ATMOSPHERE_VERTEX_SHADER,
        fragmentShader: ATMOSPHERE_FRAGMENT_SHADER,
        blending: NormalBlending,
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

  // Drawn before the markers, so they stay crisp over the haze at the globe's edge.
  return (
    <mesh scale={ATMOSPHERE_SHELL_RADIUS} renderOrder={-1}>
      <sphereGeometry args={[1, 64, 48]} />
      <primitive object={material} attach="material" />
    </mesh>
  );
}

/**
 * Full-viewport globe with one marker per mountain. Drag to orbit and scroll to zoom.
 * The canvas is transparent, so the page's backdrop shows around the globe.
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
      flat
      camera={{ position: [0, 0.25, 3.4], fov: 40 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
    >
      <hemisphereLight args={[GLOBE_COLORS.sky, GLOBE_COLORS.ground, HEMISPHERE_INTENSITY]} />
      <KeyLight />
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
        <Atmosphere />
      </Suspense>
      <CameraFlight target={flyTarget} earth={earthRef} onArrive={onArrive} />
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
