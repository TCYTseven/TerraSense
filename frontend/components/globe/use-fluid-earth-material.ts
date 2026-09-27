"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { MeshStandardMaterial, type Texture } from "three";

const OCEAN_MAP_PATCH = /* glsl */ `
#ifdef USE_MAP
  vec4 texelColor = texture2D( map, vMapUv );
  #ifdef DECODE_VIDEO_TEXTURE
    texelColor = sRGBTransferEOTF( texelColor );
  #endif
  float oceanMask = smoothstep( 0.06, 0.38, texelColor.b - max( texelColor.r, texelColor.g ) );
  vec3 deepOcean = vec3( 0.03, 0.16, 0.36 );
  vec3 shallowOcean = vec3( 0.10, 0.42, 0.62 );
  float ripple = 0.5 + 0.5 * sin( uTime * 0.35 + vMapUv.x * 16.0 + vMapUv.y * 11.0 );
  vec3 fluidOcean = mix( deepOcean, shallowOcean, ripple );
  texelColor.rgb = mix( texelColor.rgb, fluidOcean, oceanMask * 0.9 );
  diffuseColor *= texelColor;
#endif
`;

/** Earth day texture with a slow shifting tint on ocean pixels. */
export function useFluidEarthMaterial(colorMap: Texture, bumpMap: Texture, glow: number): MeshStandardMaterial {
  const material = useMemo(() => {
    const mat = new MeshStandardMaterial({
      map: colorMap,
      emissiveMap: colorMap,
      emissive: "#ffffff",
      emissiveIntensity: glow,
      bumpMap,
      bumpScale: 0.035,
      roughness: 0.88,
      metalness: 0.04,
    });
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = { value: 0 };
      mat.userData.shader = shader;
      shader.fragmentShader = `uniform float uTime;\n${shader.fragmentShader}`.replace(
        "#include <map_fragment>",
        OCEAN_MAP_PATCH,
      );
    };
    return mat;
  }, [bumpMap, colorMap, glow]);

  useEffect(() => {
    return () => {
      material.dispose();
    };
  }, [material]);

  const materialRef = useRef(material);
  materialRef.current = material;

  useFrame(({ clock }) => {
    const shader = materialRef.current.userData.shader as { uniforms: { uTime: { value: number } } } | undefined;
    if (shader?.uniforms.uTime) {
      shader.uniforms.uTime.value = clock.elapsedTime;
    }
  });

  return material;
}
