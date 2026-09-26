"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getSimulation, simulationStreamUrl, startSimulation } from "./api";
import type { FlowFeatureCollection, Position, Simulation, SimulationCallout } from "./types";

const FRAME_MS = 500;

export type SimulationPhase = "idle" | "loading" | "playing" | "finished" | "error";

export interface ReleaseCamera {
  lon: number;
  lat: number;
  zoom: number;
  nonce: number;
  /** The whole final footprint, [west, south, east, north]. The camera fits it when set. */
  bounds?: [number, number, number, number];
  /** Faces uphill from the flow's toe to the release, so the front comes toward the viewer. */
  bearing?: number;
}

export interface SimulationPlayback {
  phase: SimulationPhase;
  simulation: Simulation | null;
  /** The frame the map should draw. Null until the first snapshot. */
  frameIndex: number;
  /** Simulated seconds at the current frame. */
  timeS: number;
  error: string | null;
  /** Flies the map to the release. Set once per run, not on replay. */
  camera: ReleaseCamera | null;
  start: () => void;
  replay: () => void;
}

const FAILED = "The simulation didn't run. The pressure points still show.";

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Frames the final footprint, looking uphill from where the flow stops toward the release. */
function frontCamera(sim: Simulation, lon: number, lat: number): ReleaseCamera {
  const camera: ReleaseCamera = { lon, lat, zoom: 13.2, nonce: Date.now() };
  const last = sim.frames[sim.frames.length - 1]?.geojson;
  const stop = sim.steps.find((step) => step.kind === "stop");
  const bounds = last ? footprintBounds(last) : null;
  if (!bounds || !stop) {
    return camera;
  }
  return { ...camera, bounds, bearing: bearingDeg([stop.lon, stop.lat], [lon, lat]) };
}

function footprintBounds(flow: FlowFeatureCollection): [number, number, number, number] | null {
  const points: Position[] = flow.features.flatMap((feature) =>
    feature.geometry.type === "Polygon" ? feature.geometry.coordinates.flat() : feature.geometry.coordinates.flat(2),
  );
  if (points.length === 0) {
    return null;
  }
  const lons = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

/** Compass bearing from a to b, in degrees. */
function bearingDeg(a: Position, b: Position): number {
  const rad = Math.PI / 180;
  const [lon1, lat1, lon2, lat2] = [a[0] * rad, a[1] * rad, b[0] * rad, b[1] * rad];
  const y = Math.sin(lon2 - lon1) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lon2 - lon1);
  return (Math.atan2(y, x) / rad + 360) % 360;
}

/**
 * Starts a runout, follows its stream, and advances one frame every 500 ms.
 * Replay uses the frames already loaded.
 */
export function useSimulation(slug: string): SimulationPlayback {
  const [phase, setPhase] = useState<SimulationPhase>("idle");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [camera, setCamera] = useState<ReleaseCamera | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopStream = useRef<(() => void) | null>(null);
  const simRef = useRef<Simulation | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const play = useCallback(
    (sim: Simulation, from: number) => {
      clearTimer();
      const last = Math.max(0, sim.frames.length - 1);
      if (prefersReducedMotion() || sim.frames.length <= 1) {
        setFrameIndex(last);
        setPhase("finished");
        return;
      }
      let index = from;
      setFrameIndex(from);
      setPhase("playing");
      timer.current = setInterval(() => {
        index += 1;
        if (index >= sim.frames.length) {
          clearTimer();
          setFrameIndex(sim.frames.length - 1);
          setPhase("finished");
          return;
        }
        setFrameIndex(index);
      }, FRAME_MS);
    },
    [clearTimer],
  );

  const remember = useCallback((sim: Simulation) => {
    simRef.current = sim;
    setSimulation(sim);
  }, []);

  const start = useCallback(() => {
    stopStream.current?.();
    clearTimer();
    setError(null);
    setPhase("loading");
    setFrameIndex(0);
    void startSimulation(slug)
      .then(({ simulation_id }) => {
        stopStream.current = follow(simulation_id, {
          onSnapshot(sim) {
            remember(sim);
            const point = sim.pressure_point;
            if (point) {
              setCamera(frontCamera(sim, point.lon, point.lat));
            }
            play(sim, 0);
          },
          onCallout(callout) {
            setSimulation((prev) => {
              if (!prev || prev.callouts.some((item) => item.id === callout.id)) {
                return prev;
              }
              const next = { ...prev, callouts: [...prev.callouts, callout] };
              simRef.current = next;
              return next;
            });
          },
          onFinal(sim) {
            remember(sim);
            if (sim.status === "error") {
              clearTimer();
              setPhase("error");
              setError(FAILED);
            }
          },
          onLost() {
            clearTimer();
            setPhase("error");
            setError(FAILED);
          },
        });
      })
      .catch(() => {
        clearTimer();
        setPhase("error");
        setError(FAILED);
      });
  }, [slug, clearTimer, play, remember]);

  const replay = useCallback(() => {
    const sim = simRef.current;
    if (!sim || sim.frames.length === 0) {
      return;
    }
    setError(null);
    play(sim, 0);
  }, [play]);

  useEffect(
    () => () => {
      clearTimer();
      stopStream.current?.();
    },
    [clearTimer],
  );

  const frame = simulation?.frames[frameIndex];
  return {
    phase,
    simulation,
    frameIndex,
    timeS: frame?.t_s ?? 0,
    error,
    camera,
    start,
    replay,
  };
}

interface SimulationHandlers {
  onSnapshot: (simulation: Simulation) => void;
  onCallout: (callout: SimulationCallout) => void;
  onFinal: (simulation: Simulation) => void;
  onLost: () => void;
}

function follow(simulationId: string, handlers: SimulationHandlers): () => void {
  let socket: WebSocket | null = null;
  let stopped = false;
  let sawFinal = false;

  const recover = async () => {
    try {
      const sim = await getSimulation(simulationId);
      if (stopped || !sim) {
        if (!stopped) {
          handlers.onLost();
        }
        return;
      }
      if (sim.frames.length > 0) {
        handlers.onSnapshot(sim);
      }
      if (sim.status !== "running") {
        sawFinal = true;
        handlers.onFinal(sim);
        return;
      }
    } catch {
      if (!stopped) {
        handlers.onLost();
      }
    }
  };

  socket = new WebSocket(simulationStreamUrl(simulationId));
  socket.onmessage = (message: MessageEvent<string>) => {
    let data: unknown;
    try {
      data = JSON.parse(message.data);
    } catch {
      return;
    }
    if (!data || typeof data !== "object") {
      return;
    }
    const record = data as { type?: string; simulation?: Simulation; callout?: SimulationCallout };
    if (record.type === "snapshot" && record.simulation) {
      handlers.onSnapshot(record.simulation);
    } else if (record.type === "callout" && record.callout) {
      handlers.onCallout(record.callout);
    } else if (record.type === "final" && record.simulation) {
      sawFinal = true;
      handlers.onFinal(record.simulation);
    } else if (record.type === "error") {
      handlers.onLost();
    }
  };
  socket.onclose = () => {
    if (!sawFinal && !stopped) {
      void recover();
    }
  };
  return () => {
    stopped = true;
    socket?.close();
  };
}
