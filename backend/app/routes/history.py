"""The run history log: every past analysis run (step 33).

Reads the previous_runs table that app/previous_runs.py writes after each run. The list is a
page of flat summary rows for the /history table; the detail is one run with every payload the
log kept, which is what the expanded row shows.

Not to be confused with app/history.py, which is the catalog of past real-world landslides.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app import previous_runs

router = APIRouter(tags=["history"])

HazardClass = Literal["landslide", "avalanche", "debris_flow", "unknown"]


class RunRecord(BaseModel):
    """One logged run, as the history table shows it. Mirrored in frontend/lib/types.ts."""

    # The ML columns are named model_*, which is Pydantic's own reserved prefix. These are data.
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    mountain_slug: str
    mountain_name: str | None
    lat: float | None
    lon: float | None
    elevation_m: int | None

    hazard_class: HazardClass
    hazard_type: str | None
    hazard_id: str | None
    snow_driven: bool

    status: str
    phase: str | None
    message: str | None
    error: str | None
    failed_agent: str | None
    started_at: datetime
    finished_at: datetime | None
    elapsed_s: float | None

    severity: str | None
    confidence: float | None
    needs_review: bool | None
    recommended_action: str | None
    posture: str | None
    priority: str | None
    headline: str | None
    summary: str | None

    model_method: str | None
    model_is_stand_in: bool | None
    model_max_probability: float | None
    model_share_at_high: float | None

    # Per agent: severity, confidence, and which provider and model answered.
    agent_verdicts: dict[str, Any] = {}
    # One entry per model call: provider, model, attempts, latency, tokens.
    llm_calls: list[dict[str, Any]] = []
    llm_usage: dict[str, Any] = {}


class RunRecordDetail(RunRecord):
    """One logged run with everything the log kept, for the expanded row."""

    model_note: str | None = None
    model_mean_probability: float | None = None
    model_output: dict[str, Any] = {}
    # Every agent's final event with its full trace: route, tools, attempts, raw model JSON.
    agent_outputs: dict[str, Any] = {}
    advisory: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    rain: dict[str, Any] | None = None
    run: dict[str, Any] = {}


class HistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    stats: dict[str, Any]
    runs: list[RunRecord]


@router.get("/history")
def list_history(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    slug: str | None = None,
    hazard_class: HazardClass | None = None,
    status: Literal["running", "done", "error"] | None = None,
) -> HistoryPage:
    """Past runs, newest first, with the header counts. Empty until the first run finishes."""
    runs, total = previous_runs.list_runs(
        limit=limit, offset=offset, slug=slug, hazard_class=hazard_class, status=status
    )
    return HistoryPage(
        total=total,
        limit=limit,
        offset=offset,
        stats=previous_runs.stats(),
        runs=[RunRecord.model_validate(row) for row in runs],
    )


def _is_uuid(value: str) -> bool:
    """run_id is a uuid column: a junk path segment is a 404, not a database error."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@router.get("/history/{run_id}", responses={404: {"description": "No logged run with this id."}})
def get_history_run(run_id: str) -> RunRecordDetail:
    """One logged run with every agent trace, the model's output, and the advisory."""
    row = previous_runs.get_run_record(run_id) if _is_uuid(run_id) else None
    if row is None:
        raise HTTPException(status_code=404, detail=f"No logged run {run_id!r}")
    return RunRecordDetail.model_validate(row)
