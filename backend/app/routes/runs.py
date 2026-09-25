"""Start an analysis, read a run, and stream one (step 22)."""

import asyncio
import contextlib
import uuid
from typing import Annotated

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from psycopg.rows import DictRow
from pydantic import BaseModel

from app.agents.schemas import Run, RunUpdate
from app.db import get_conn
from app.runs import load_run, registry

router = APIRouter(tags=["runs"])

Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]

# A WebSocket close code for "no such run", in the range left for applications.
CLOSE_NOT_FOUND = 4404


class AnalyzeStarted(BaseModel):
    run_id: str


def _uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@router.post("/mountains/{slug}/analyze", status_code=202, responses={
    200: {"description": "A run was already going for this mountain. Its id comes back."},
    404: {"description": "No mountain with this slug."},
    409: {"description": "A static marker: it does not run analysis."},
})
async def analyze(slug: str, conn: Conn, response: Response) -> AnalyzeStarted:
    """Start the pipeline for a live mountain in the background. Only one run per mountain at a time."""
    mountain = conn.execute("SELECT id, name, lat, lon, is_live FROM mountains WHERE slug = %s", (slug,)).fetchone()
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if not mountain["is_live"]:
        raise HTTPException(status_code=409,
                            detail=f"{mountain['name']} is a display marker. Live analysis runs on Mount Rainier only.")
    state, started = registry.start(slug, mountain)
    response.status_code = 202 if started else 200
    return AnalyzeStarted(run_id=state.id)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Run:
    """A run's status and every agent's latest event, from memory or, once finished, from its row."""
    state = registry.get(run_id)
    if state is not None:
        return state.view()
    run = await asyncio.to_thread(load_run, run_id) if _uuid(run_id) else None
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}")
    return run


@router.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str) -> None:
    """A RunUpdate snapshot first, then each AgentEvent and RunUpdate until the run ends."""
    await ws.accept()
    state = registry.get(run_id)
    if state is None:
        run = None
        if _uuid(run_id):
            with contextlib.suppress(psycopg.Error):
                run = await asyncio.to_thread(load_run, run_id)
        if run is None:
            await ws.send_json({"kind": "error", "detail": f"No run {run_id!r}"})
        else:
            await ws.send_json(RunUpdate(run=run).model_dump(mode="json"))
        await ws.close(code=CLOSE_NOT_FOUND if run is None else 1000)
        return

    # Subscribe before the snapshot, so nothing between them is lost. A repeat is harmless: the
    # client keeps the latest event per agent.
    queue = registry.subscribe(state)
    try:
        snapshot = state.view()
        await ws.send_json(RunUpdate(run=snapshot).model_dump(mode="json"))
        # End on the run's final update, which every run broadcasts after it stores its result.
        # Never poll state.status here: it turns final a moment before that broadcast.
        while snapshot.status == "running":
            message = await queue.get()
            await ws.send_json(message)
            if message.get("kind") == "run" and message["run"]["status"] != "running":
                break
    except (WebSocketDisconnect, RuntimeError):
        return  # the browser went away
    finally:
        registry.unsubscribe(state, queue)
    with contextlib.suppress(RuntimeError):
        await ws.close()
