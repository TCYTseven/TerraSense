"use client";

import { OrbitControls, useTexture } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import {
  type ReactNode,
  type RefObject,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
import RegionViewCamera from "./region-view-camera";
import { useFluidEarthMaterial } from "./use-fluid-earth-material";
import type { GlobeRegion } from "@/lib/globe-regions";

/** Drop the globe's WebGL context on unmount so the mountain map can create one. */
function ReleaseWebGL() {
  const { gl } = useThree();
  useEffect(() => {
    return () => {
      gl.forceContextLoss();
      gl.dispose();
    };
  }, [gl]);
  return null;
}

/** Radians per second. One full turn takes about 100 seconds. */
const IDLE_SPIN_RADIANS_PER_SECOND = 0.06;

/** Earth's axial tilt, in radians. */
const AXIAL_TILT_RADIANS = 0.41;

const EARTH_RADIUS = 1;

/**
 * Orbit zoom limits, as camera distance from the globe's center. The surface is at 1, so the
 * closest view frames about one region (northern Italy and the Alps), close enough to pick
 * apart peaks in one range without the blurry texture filling the screen.
 */
const MIN_CAMERA_DISTANCE = 1.25;
const MAX_CAMERA_DISTANCE = 5;

/** Drag speed at the default view's height above the surface. It slows as the camera nears the ground. */
const ROTATE_SPEED = 0.45;
const ROTATE_SPEED_REFERENCE_ALTITUDE = 2.4;

/** Scales the drag speed with altitude, so one drag moves the same distance on screen at any zoom. */
function AltitudeRotateSpeed() {
  useFrame((state) => {
    const { camera } = state;
    const controls = state.controls as { rotateSpeed: number } | null;
    if (!controls) {
      return;
    }
    const altitude = camera.position.length() - EARTH_RADIUS;
    controls.rotateSpeed = ROTATE_SPEED * Math.min(1, altitude / ROTATE_SPEED_REFERENCE_ALTITUDE);
  });
  return null;
}

/** How much the day texture lights itself, 0 to 1. Keeps the whole globe readable. */
const EARTH_GLOW = 0.45;

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

function handleGlobePointer(
  event: ThreeEvent<PointerEvent>,
  onEngage: (() => void) | undefined,
) {
  if (event.button !== 0) {
    return;
  }
  blockPointer(event);
  onEngage?.();
}

/**
 * Satellite Earth that rotates on its axis. Children ride on the surface and turn with it.
 */
function Earth({
  meshRef,
  spinning,
  onReady,
  onGlobeEngage,
  children,
}: {
  meshRef: RefObject<Mesh | null>;
  spinning: boolean;
  onReady: () => void;
  onGlobeEngage?: () => void;
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
  const surfaceMaterial = useFluidEarthMaterial(colorMap, bumpMap, EARTH_GLOW);

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
        onPointerDown={(event) => handleGlobePointer(event, onGlobeEngage)}
      >
        <sphereGeometry args={[EARTH_RADIUS, 96, 96]} />
        <primitive object={surfaceMaterial} attach="material" />
        {children}
      </mesh>
    </group>
  );
}

/**
 * Thin atmospheric rim that stays fixed while the surface turns.
 */
function Atmosphere({ glowColor }: { glowColor: string }) {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: {
          glowColor: { value: new Color(glowColor) },
        },
        vertexShader: ATMOSPHERE_VERTEX_SHADER,
        fragmentShader: ATMOSPHERE_FRAGMENT_SHADER,
        blending: AdditiveBlending,
        side: BackSide,
        transparent: true,
        depthWrite: false,
      }),
    [glowColor],
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
  region,
  spinPaused,
  onGlobeEngage,
  sceneBackground = THEME.background,
  atmosphereColor = THEME.foreground,
}: {
  mountains: Mountain[];
  flyTarget: Mountain | null;
  onSelect: (mountain: Mountain) => void;
  onArrive: (mountain: Mountain) => void;
  onReady: () => void;
  region: GlobeRegion;
  spinPaused: boolean;
  onGlobeEngage?: () => void;
  /** Canvas clear color; home passes HOME_THEME. */
  sceneBackground?: string;
  atmosphereColor?: string;
}) {
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null);
  const [regionTransition, setRegionTransition] = useState(false);
  const earthRef = useRef<Mesh>(null);
  const flying = flyTarget !== null;
  const onRegionTransition = useCallback((active: boolean) => {
    setRegionTransition(active);
  }, []);
  const idleSpin =
    region.allowIdleSpin && !spinPaused && hoveredSlug === null && !flying && !regionTransition;

  return (
    <Canvas
      camera={{ position: [0, 0.25, 3.4], fov: 40, near: 0.01 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: false }}
    >
      <ReleaseWebGL />
      <color attach="background" args={[sceneBackground]} />
      {/* Bright, even daylight: the whole face of the globe reads, with a soft sun for relief. */}
      <ambientLight intensity={0.9} />
      <hemisphereLight args={["#e8f4ff", "#1a4d6e", 0.72]} />
      <directionalLight position={[4.5, 1.6, 3.2]} intensity={1.6} color="#fff4e5" />
      <directionalLight position={[-3.5, -1.2, -2]} intensity={0.7} color="#cfe0f0" />
      <Suspense fallback={null}>
        <Earth meshRef={earthRef} spinning={idleSpin} onReady={onReady} onGlobeEngage={onGlobeEngage}>
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
      <RegionViewCamera
        region={region}
        disabled={flying}
        earthRef={earthRef}
        onTransitionChange={onRegionTransition}
      />
      <CameraFlight target={flyTarget} earth={earthRef} onArrive={onArrive} />
      <Atmosphere glowColor={atmosphereColor} />
      <OrbitControls
        makeDefault
        enabled={!flying && !regionTransition}
        enablePan={false}
        enableDamping
        dampingFactor={0.1}
        rotateSpeed={ROTATE_SPEED}
        minDistance={MIN_CAMERA_DISTANCE}
        maxDistance={MAX_CAMERA_DISTANCE}
      />
      <AltitudeRotateSpeed />
    </Canvas>
  );
}
