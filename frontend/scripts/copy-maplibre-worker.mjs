// Copies MapLibre's tile worker into public/maplibre/, where the map loads it from.
// MapLibre 6 ships the worker as separate ES modules next to its main file, and the
// bundler does not emit them, so components/map/terrain-map.tsx points setWorkerUrl here.
// Runs on npm install (postinstall). The copies are gitignored.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dist = path.join(path.dirname(require.resolve("maplibre-gl/package.json")), "dist");
const target = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "maplibre");

// The worker imports the shared chunk by relative path, so both land in one folder.
const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

mkdirSync(target, { recursive: true });
for (const file of FILES) {
  copyFileSync(path.join(dist, file), path.join(target, file));
}
console.log(`Copied the MapLibre worker to ${path.relative(process.cwd(), target) || "."}`);
