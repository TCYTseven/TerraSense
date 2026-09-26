import { Vector3 } from "three";

/**
 * Point on a three.js SphereGeometry for a latitude and longitude, matching how an
 * equirectangular texture wraps the sphere: longitude -180 at u = 0, latitude 90 at +Y.
 */
export function latLonToVector3(lat: number, lon: number, radius = 1): Vector3 {
  const azimuth = ((lon + 180) * Math.PI) / 180;
  const polar = ((90 - lat) * Math.PI) / 180;
  return new Vector3(
    -radius * Math.cos(azimuth) * Math.sin(polar),
    radius * Math.cos(polar),
    radius * Math.sin(azimuth) * Math.sin(polar),
  );
}
