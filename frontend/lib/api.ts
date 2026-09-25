import type { LayerTiles, Mountain, MountainDetail } from "./types";

/** The FastAPI service. Set NEXT_PUBLIC_API_URL in the repo root .env. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

/** A response from the API with a non-2xx status. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Every mountain for the globe, live ones first. */
export function getMountains(init?: RequestInit): Promise<Mountain[]> {
  return getJson<Mountain[]>("/mountains", init);
}

/** One mountain with its trails and active hazard. Resolves to null for an unknown slug. */
export async function getMountain(slug: string, init?: RequestInit): Promise<MountainDetail | null> {
  try {
    return await getJson<MountainDetail>(`/mountains/${encodeURIComponent(slug)}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The tile template for a map layer. Resolves to null when the layer is not available. */
export async function getLayer(slug: string, layer: string, init?: RequestInit): Promise<LayerTiles | null> {
  try {
    return await getJson<LayerTiles>(
      `/mountains/${encodeURIComponent(slug)}/layers/${encodeURIComponent(layer)}`,
      init,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}
