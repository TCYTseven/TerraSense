import { Vector3 } from "three";

/**
 * Where the globe's key light comes from, in camera space: the viewer's upper left, in
 * front. The Earth's key light and the markers' baked facet shading both use it, so the
 * peaks are lit from the same side as the ground they stand on.
 */
export const KEY_LIGHT_DIRECTION = new Vector3(-0.9, 1.1, 1.6).normalize();
