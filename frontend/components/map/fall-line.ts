import type { MapLibreMap } from "maplibre-gl";

/** How far either side of the point the slope is measured, in meters. Wide enough for coarse terrain tiles. */
const PROBE_M = 150;

/**
 * The compass bearing straight up the slope at a point, from the map's own 3D terrain.
 * A camera with this bearing looks uphill, so the face a landslide would come down
 * turns toward the viewer. Null when the terrain there is not loaded or the ground is flat.
 */
export function uphillBearing(map: MapLibreMap, lon: number, lat: number): number | null {
  const dLat = PROBE_M / 111_320;
  const dLon = PROBE_M / (111_320 * Math.cos((lat * Math.PI) / 180));
  const at = (x: number, y: number) => map.queryTerrainElevation([x, y]);
  const east = at(lon + dLon, lat);
  const west = at(lon - dLon, lat);
  const north = at(lon, lat + dLat);
  const south = at(lon, lat - dLat);
  if (east === null || west === null || north === null || south === null) {
    return null;
  }
  const rise = { east: east - west, north: north - south };
  if (Math.hypot(rise.east, rise.north) < 1) {
    return null;
  }
  return ((Math.atan2(rise.east, rise.north) * 180) / Math.PI + 360) % 360;
}
