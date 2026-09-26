import type {
  Forecast,
  AvalancheRiskPrediction,
  HistoryPage,
  LandslideRiskPrediction,
  LayerTiles,
  Mountain,
  MountainDetail,
  MountainRiskSummary,
  Run,
  RunRecordDetail,
  Simulation,
} from "./types";

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

async function postJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { method: "POST", cache: "no-store", ...init });
  if (!response.ok) {
    let detail = `POST ${path} returned ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Not JSON: keep the status line.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Reload committed seed JSON into Postgres (ops only; no external catalog APIs). */
export function syncMountainCatalog(init?: RequestInit): Promise<{ count: number; source: string }> {
  return postJson("/mountains/catalog/sync", init);
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

/**
 * Start the five-agent analysis for a live mountain (step 22). Resolves to the run id: a new
 * run, or the one already going for this mountain.
 */
export async function startAnalysis(slug: string, init?: RequestInit): Promise<string> {
  const { run_id } = await postJson<{ run_id: string }>(`/mountains/${encodeURIComponent(slug)}/analyze`, init);
  return run_id;
}

/** A run's status and every agent's latest event. Resolves to null for an unknown run. */
export async function getRun(runId: string, init?: RequestInit): Promise<Run | null> {
  try {
    return await getJson<Run>(`/runs/${encodeURIComponent(runId)}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The hiker card's facts from the latest finished run. Resolves to null before any. */
export async function getForecast(mountainId: string, trailId?: string | null, init?: RequestInit): Promise<Forecast | null> {
  const query = new URLSearchParams({ mountain_id: mountainId });
  if (trailId) {
    query.set("trail_id", trailId);
  }
  try {
    return await getJson<Forecast>(`/forecast?${query}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** One hill with its trails. Resolves to null unless the slug is a hill. */
export async function getHill(slug: string, init?: RequestInit): Promise<MountainDetail | null> {
  try {
    return await getJson<MountainDetail>(`/hills/${encodeURIComponent(slug)}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** A hill's tile template. Resolves to null when the layer is not available. */
export async function getHillLayer(slug: string, layer: string, init?: RequestInit): Promise<LayerTiles | null> {
  try {
    return await getJson<LayerTiles>(
      `/hills/${encodeURIComponent(slug)}/layers/${encodeURIComponent(layer)}`,
      init,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** A hill's scores on its saved heat map. Resolves to null before the first save. */
export async function getHillRiskSummary(slug: string, init?: RequestInit): Promise<MountainRiskSummary | null> {
  try {
    return await getJson<MountainRiskSummary>(`/hills/${encodeURIComponent(slug)}/risk-summary`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The overall score and top trails on the saved heat map. Resolves to null before the first save. */
export async function getRiskSummary(slug: string, init?: RequestInit): Promise<MountainRiskSummary | null> {
  try {
    return await getJson<MountainRiskSummary>(`/mountains/${encodeURIComponent(slug)}/risk-summary`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** Classify rainfall-triggered landslide risk for the next week at a 1 km cell. */
export function getLandslideRisk(
  latitude: number,
  longitude: number,
  timestamp?: string,
  init?: RequestInit,
): Promise<LandslideRiskPrediction> {
  return postJson<LandslideRiskPrediction>("/api/v1/landslide-risk", {
    ...init,
    body: JSON.stringify({ latitude, longitude, ...(timestamp ? { timestamp } : {}) }),
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
}

/** Classify avalanche occurrence risk for the next 24 hours at a 1 km cell. */
export function getAvalancheRisk(
  latitude: number,
  longitude: number,
  timestamp?: string,
  init?: RequestInit,
): Promise<AvalancheRiskPrediction> {
  return postJson<AvalancheRiskPrediction>("/api/v1/avalanche-risk", {
    ...init,
    body: JSON.stringify({ latitude, longitude, ...(timestamp ? { timestamp } : {}) }),
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
}

/** The WebSocket URL for a run's live stream. */
export function runStreamUrl(runId: string): string {
  return `${API_URL.replace(/^http/, "ws")}/runs/${encodeURIComponent(runId)}/stream`;
}

/** Start an illustrative runout. The API always runs it down the one route most likely to fail. */
export function startSimulation(slug: string, init?: RequestInit): Promise<{ simulation_id: string }> {
  return postJson(`/mountains/${encodeURIComponent(slug)}/simulate`, {
    ...init,
    body: JSON.stringify({}),
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
}

/** A simulation, finished or still tracing. Null when the id is unknown. */
export async function getSimulation(simulationId: string, init?: RequestInit): Promise<Simulation | null> {
  try {
    return await getJson<Simulation>(`/simulations/${encodeURIComponent(simulationId)}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The WebSocket URL for a simulation's frames, steps, and callouts. */
export function simulationStreamUrl(simulationId: string): string {
  return `${API_URL.replace(/^http/, "ws")}/simulations/${encodeURIComponent(simulationId)}/stream`;
}

/** A page of the run history log (step 33), newest first. */
export function getHistory(
  params: { limit?: number; offset?: number; slug?: string; hazardClass?: string; status?: string } = {},
  init?: RequestInit,
): Promise<HistoryPage> {
  const query = new URLSearchParams();
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.offset != null) query.set("offset", String(params.offset));
  if (params.slug) query.set("slug", params.slug);
  if (params.hazardClass) query.set("hazard_class", params.hazardClass);
  if (params.status) query.set("status", params.status);
  const suffix = query.toString();
  return getJson<HistoryPage>(`/history${suffix ? `?${suffix}` : ""}`, init);
}

/** One logged run with every agent trace and the model's output. Null when it is not logged. */
export async function getHistoryRun(runId: string, init?: RequestInit): Promise<RunRecordDetail | null> {
  try {
    return await getJson<RunRecordDetail>(`/history/${encodeURIComponent(runId)}`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}
