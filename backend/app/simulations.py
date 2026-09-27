"""In-process runout simulations (step 28). Nothing is written to Postgres.

A simulation traces frames down the one route most likely to fail, then asks Gemini
or Grok for one downvalley community alert (with a static fallback when no key is set).
The place's kind picks the physics: a snow avalanche on a mountain, a debris flow on a hill.
The snapshot goes out before the alert, so the map can play while the model answers.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from app.ml.pressure import worst_route
from app.ml.runout import trace_runout
from app.ml.runout_physics import process_for
from app.simulation_communities import generate_community_callout

NOTHING_TO_SIMULATE = "Nothing reaches Moderate today, so there's nothing to simulate."


@dataclass
class SimulationState:
    id: str
    slug: str
    mountain: dict | None = None
    status: str = "running"
    method: str = ""
    source: str = "trail"
    pressure_point: dict | None = None
    duration_s: float = 0
    distance_m: float = 0
    drop_m: float = 0
    frames: list = field(default_factory=list)
    flow_field: dict | None = None
    physics: dict | None = None
    steps: list = field(default_factory=list)
    callouts: list = field(default_factory=list)
    callouts_from_templates: bool = False
    error: str | None = None
    listeners: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None

    def view(self) -> dict:
        return {
            "id": self.id,
            "mountain_slug": self.slug,
            "status": self.status,
            "method": self.method,
            "source": self.source,
            "pressure_point": self.pressure_point,
            "duration_s": self.duration_s,
            "distance_m": self.distance_m,
            "drop_m": self.drop_m,
            "frames": self.frames,
            "field": self.flow_field,
            "physics": self.physics,
            "steps": self.steps,
            "callouts": self.callouts,
            "callouts_from_templates": self.callouts_from_templates,
            "error": self.error,
        }


class SimulationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SimulationState] = {}

    def get(self, simulation_id: str) -> SimulationState | None:
        return self._items.get(simulation_id)

    def start(self, slug: str, trails: list[dict], mountain: dict | None = None) -> SimulationState:
        """Only the route most likely to fail is ever simulated."""
        point = worst_route(trails)
        if point is None:
            raise ValueError(NOTHING_TO_SIMULATE)
        state = SimulationState(id=str(uuid.uuid4()), slug=slug, mountain=mountain, pressure_point=point)
        self._items[state.id] = state
        state.task = asyncio.create_task(self._run(state, point, trails))
        return state

    async def _run(self, state: SimulationState, point: dict, trails: list[dict]) -> None:
        try:
            process = process_for((state.mountain or {}).get("kind"))
            traced = await asyncio.to_thread(trace_runout, point, trails, process)
            # The flow releases at the route's highest point, so the pin and the camera go there.
            release = traced["release"]
            point = {**point, "lon": release["lon"], "lat": release["lat"], "elevation_m": release["elevation_m"]}
            state.pressure_point = point
            state.method = traced["method"]
            state.source = traced["source"]
            state.duration_s = traced["duration_s"]
            state.distance_m = traced["distance_m"]
            state.drop_m = traced["drop_m"]
            state.frames = traced["frames"]
            state.flow_field = traced.get("field")
            state.physics = traced.get("physics")
            state.steps = traced["steps"]
            self._broadcast(state, {"type": "snapshot", "simulation": state.view()})
            mountain = state.mountain or {"slug": state.slug, "name": state.slug.replace("-", " ").title()}
            callout, used_llm = await generate_community_callout(
                mountain,
                point,
                state.steps,
                state.frames,
                distance_m=state.distance_m,
                drop_m=state.drop_m,
            )
            state.callouts.append(callout)
            self._broadcast(state, {"type": "callout", "callout": callout})
            state.callouts_from_templates = not used_llm
            state.status = "done"
            self._broadcast(state, {"type": "final", "simulation": state.view()})
        except Exception as exc:
            state.status = "error"
            state.error = str(exc)
            self._broadcast(state, {"type": "final", "simulation": state.view()})

    def subscribe(self, state: SimulationState) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        state.listeners.add(queue)
        return queue

    def unsubscribe(self, state: SimulationState, queue: asyncio.Queue) -> None:
        state.listeners.discard(queue)

    def _broadcast(self, state: SimulationState, message: dict) -> None:
        for queue in list(state.listeners):
            queue.put_nowait(message)


registry = SimulationRegistry()


def template_callouts(steps: list[dict], point: dict) -> list[dict]:
    """Two notes the code can stand behind when the model does not answer.

    Ranger text stays under 40 words. Public text stays under 35. Every trail,
    mile, and time comes from a step.
    """
    trail_steps = [step for step in steps if step["kind"] == "trail"]
    trail = trail_steps[0] if trail_steps else None
    name = (trail or {}).get("trail_name") or point.get("trail_name") or "the trail"
    start = (trail or {}).get("start_mile")
    end = (trail or {}).get("end_mile")
    miles = f" from mile {start:.1f} to {end:.1f}" if isinstance(start, (int, float)) and isinstance(end, (int, float)) else ""
    when = (trail or {}).get("t_s")
    clock = _clock(when) if isinstance(when, (int, float)) else "the release"
    stop = next((step for step in steps if step["kind"] == "stop"), None)
    distance_mi = ((stop or {}).get("distance_m") or 0) / 1609.344
    ranger = f"Close {name}{miles} and post a ranger at the trailhead. The illustrative front is at {clock}."
    public = f"Debris may reach {name}{miles}. Stay off that trail and out of the creek channel."
    notes = [
        {"id": "rangers-close", "step_id": (trail or {}).get("id") or "release", "audience": "rangers", "text": ranger, "t_s": (trail or {}).get("t_s") or 0},
        {"id": "public-draft", "step_id": (trail or {}).get("id") or "release", "audience": "public", "text": public, "t_s": (trail or {}).get("t_s") or 0},
    ]
    if stop and distance_mi:
        notes.append(
            {
                "id": "rangers-stop",
                "step_id": stop["id"],
                "audience": "rangers",
                "text": f"The sketched runout stops after {distance_mi:.1f} mi. Treat the clock as illustrative, not a forecast.",
                "t_s": stop["t_s"],
            }
        )
    return notes


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"T+{total // 60:02d}:{total % 60:02d}"
