"""Pressure points and the runout simulation (steps 26 and 28)."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from psycopg.rows import DictRow
from pydantic import BaseModel

from app.db import get_conn
from app.ml.pressure import rank_pressure_points
from app.simulations import NOTHING_TO_SIMULATE, registry

router = APIRouter(tags=["simulations"])

Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]

# Same application close code as the run stream: the browser should not reconnect.
CLOSE_NOT_FOUND = 4404


class SimulateRequest(BaseModel):
    pressure_point_id: str | None = None


class SimulationStarted(BaseModel):
    simulation_id: str


def _trails(conn: psycopg.Connection[DictRow], slug: str) -> tuple[dict | None, list[dict]]:
    mountain = conn.execute("SELECT id, slug FROM mountains WHERE slug = %s", (slug,)).fetchone()
    if mountain is None:
        return None, []
    rows = conn.execute(
        """
        SELECT id::text AS id, name, geom, length_km, elevation_gain_m
        FROM trails WHERE mountain_id = %s ORDER BY name
        """,
        (mountain["id"],),
    ).fetchall()
    trails = []
    for row in rows:
        geom = row["geom"] or {}
        coords = geom.get("coordinates") if geom.get("type") == "LineString" else []
        trails.append(
            {
                "id": row["id"],
                "name": row["name"],
                "coordinates": coords or [],
                "length_km": row["length_km"] or 0,
                "elevation_gain_m": row["elevation_gain_m"] or 0,
            }
        )
    return mountain, trails


@router.get("/mountains/{slug}/pressure-points")
def pressure_points(slug: str, conn: Conn) -> list[dict]:
    """Up to five slopes, worst first. An empty list means the mountain has no routes."""
    mountain, trails = _trails(conn, slug)
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if not trails:
        return []
    return rank_pressure_points(trails)


@router.post("/mountains/{slug}/simulate", response_model=SimulationStarted)
async def simulate(slug: str, conn: Conn, body: SimulateRequest | None = None) -> SimulationStarted:
    """Start a runout from the worst route, or from the requested pressure point."""
    mountain, trails = _trails(conn, slug)
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if not trails:
        raise HTTPException(status_code=409, detail=NOTHING_TO_SIMULATE)
    point_id = None if body is None else body.pressure_point_id
    try:
        state = registry.start(slug, trails, point_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No pressure point {point_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SimulationStarted(simulation_id=state.id)


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str) -> dict:
    state = registry.get(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No simulation {simulation_id!r}")
    return state.view()


@router.websocket("/simulations/{simulation_id}/stream")
async def stream(ws: WebSocket, simulation_id: str) -> None:
    """Snapshot first, then each callout, then a final message."""
    await ws.accept()
    state = registry.get(simulation_id)
    if state is None:
        await ws.send_json({"type": "error", "detail": f"No simulation {simulation_id!r}"})
        await ws.close(code=CLOSE_NOT_FOUND)
        return
    queue = registry.subscribe(state)
    try:
        view = state.view()
        if view["frames"]:
            await ws.send_json({"type": "snapshot", "simulation": view})
        else:
            # Frames are still tracing. Wait for the snapshot the task broadcasts.
            message = await queue.get()
            await ws.send_json(message)
            view = message.get("simulation", view)
        if view.get("status") == "running":
            while True:
                message = await queue.get()
                await ws.send_json(message)
                if message.get("type") == "final":
                    break
        elif view.get("status") != "running":
            await ws.send_json({"type": "final", "simulation": state.view()})
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        registry.unsubscribe(state, queue)
