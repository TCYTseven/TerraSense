import { existsSync } from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

// The API and this app share one .env at the repo root. Next.js only reads
// frontend/.env* on its own, so load the root file here, at the top level,
// where Next.js keeps the values. Variables that are already set win.
// Restart `next dev` after editing it.
const rootEnv = path.join(__dirname, "..", ".env");
if (existsSync(rootEnv)) {
  process.loadEnvFile(rootEnv);
}

const nextConfig: NextConfig = {};

export default nextConfig;
