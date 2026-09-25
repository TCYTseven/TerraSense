"""GET /forecast (step 25): the hiker card's facts from the latest finished run."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import Bypass, RiskLevel
from app.routes.mountains import Conn

router = APIRouter(tags=["forecast"])


class Forecast(BaseModel):
    mountain_slug: str
    run_id: UUID
    hazard_id: UUID
    trail_id: UUID | None
    trail_name: str | None
    level: RiskLevel
    sentence: str  # the Alert Writer's hiker sentence
    start_mile: float | None
    end_mile: float | None
    bypass: Bypass | None  # added distance and climb come from here, never from the model's text


@router.get("/forecast")
def get_forecast(mountain_id: str, conn: Conn, trail_id: str | None = None) -> Forecast:
    """mountain_id takes the mountain's id or its slug. 404 until a run has finished with a hazard."""
    row = conn.execute(
        """
        SELECT m.slug, h.run_id, h.id AS hazard_id, h.trail_id, t.name AS trail_name, h.severity,
               h.start_mile, h.end_mile, h.bypass, h.how_to_avoid,
               r.agent_outputs -> 'run' -> 'agents' -> 'writer' -> 'payload' ->> 'hiker' AS hiker
        FROM hazards h
        JOIN mountains m ON m.id = h.mountain_id
        JOIN analysis_runs r ON r.id = h.run_id
        LEFT JOIN trails t ON t.id = h.trail_id
        WHERE (m.slug = %s OR m.id::text = %s) AND r.status = 'done'
          AND (%s::text IS NULL OR h.trail_id::text = %s)
        ORDER BY h.created_at DESC LIMIT 1
        """,
        (mountain_id, mountain_id, trail_id, trail_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No finished run has a hiker forecast yet")
    return Forecast(
        mountain_slug=row["slug"], run_id=row["run_id"], hazard_id=row["hazard_id"], trail_id=row["trail_id"],
        trail_name=row["trail_name"], level=row["severity"], sentence=row["hiker"] or row["how_to_avoid"],
        start_mile=row["start_mile"], end_mile=row["end_mile"], bypass=row["bypass"],
    )
