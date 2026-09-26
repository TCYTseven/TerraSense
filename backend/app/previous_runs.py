"""The run history log (step 33): every analysis run, kept for the /history page.

`record` is called once per run, from app.runs._store_run, right after the run writes its
outcome to analysis_runs. It flattens the run's own view into the wide `previous_runs` row and
keeps the whole thing as jsonb besides, so a later page can show a field this table never gave
a column to. Nothing here is on the critical path: a failure is logged and swallowed, because
the run's own outcome matters more than its record.

What gets tagged, and why:

- `hazard_class` is the coarse kind of hazard, the thing the history page groups by. The
  pipeline's own `hazard_type` is only ever 'landslide' or 'debris_flow' today, so that is what
  this maps from. 'avalanche' is in the column's CHECK and in `classify_hazard` so a snow
  hazard has somewhere to land the day an agent emits one; until then no row will carry it.
- `snow_driven` is the honest snow signal we can compute now, straight from the run's own
  weather: meaningful snowfall in the forecast with the air at or below freezing. It is the
  input an avalanche tag would be built on, recorded separately rather than guessed into
  hazard_class.
- `agent_outputs` is every agent's final event with its full trace: the route decision, the
  tool calls, the attempts, the model's raw validated JSON, the reasoning steps, and the token
  usage. `agent_verdicts` is the compact per-agent severity/confidence/provider table.
- `model_*` and `model_output` are the ML side: which method scored the map and what it said.
"""

import logging
from typing import Any

from psycopg.types.json import Jsonb

from app.db import get_pool

logger = logging.getLogger(__name__)

# Forecast snow that makes a run snow-dominated: at least this much in the next 72 hours with
# the air staying at or below freezing. Only used for the `snow_driven` flag.
SNOW_CM_THRESHOLD = 10.0
FREEZING_C = 0.0

# Columns the list endpoint reads. The jsonb payloads are left out: a history list of 200 runs
# should not drag every agent trace across the wire.
SUMMARY_COLUMNS = """
    run_id::text AS run_id, mountain_slug, mountain_name, lat, lon, elevation_m,
    hazard_class, hazard_type, hazard_id::text AS hazard_id, snow_driven,
    status, phase, message, error, failed_agent,
    started_at, finished_at, elapsed_s,
    severity, confidence, needs_review, recommended_action, posture, priority, headline, summary,
    model_method, model_is_stand_in, model_max_probability, model_share_at_high,
    agent_verdicts, llm_calls, llm_usage
"""


def classify_hazard(hazard_type: str | None) -> str:
    """The coarse tag for the history page: landslide, debris_flow, avalanche, or unknown.

    Driven off the pipeline's own hazard type, which is a closed Literal in app.models. A run
    that failed before the terrain agent decided has no type at all, and stays 'unknown'.
    """
    if hazard_type is None:
        return "unknown"
    name = hazard_type.strip().lower()
    if "avalanche" in name:
        return "avalanche"
    if name == "debris_flow":
        return "debris_flow"
    if name == "landslide":
        return "landslide"
    return "unknown"


def is_snow_driven(conditions: dict[str, Any] | None) -> bool:
    """True when the run's forecast was snow-dominated. Never guesses from a missing field."""
    if not conditions:
        return False
    snow = conditions.get("snowfall_next_72h_cm")
    temp_max = conditions.get("temp_max_next_72h_c")
    if snow is None or temp_max is None:
        return False
    return snow >= SNOW_CM_THRESHOLD and temp_max <= FREEZING_C


def _hazard_type(run: dict[str, Any]) -> str | None:
    """The run's hazard type: from the advisory when it has one, else the terrain agent's own."""
    hazard = (run.get("advisory") or {}).get("hazard") or {}
    if hazard.get("type"):
        return hazard["type"]
    terrain = (run.get("agents") or {}).get("terrain") or {}
    payload = terrain.get("payload") or {}
    output = ((terrain.get("trace") or {}).get("output")) or {}
    return payload.get("type") or output.get("type")


def _llm_calls(run: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per agent that reached a model: who answered, how fast, and what it cost."""
    calls = []
    for name, event in (run.get("agents") or {}).items():
        trace = (event or {}).get("trace") or {}
        route = trace.get("route") or {}
        if not route:
            continue
        calls.append({
            "agent": name,
            "status": event.get("status"),
            "provider": route.get("provider"),
            "model": route.get("model"),
            "label": route.get("label"),
            "tier": route.get("tier"),
            "reason": route.get("reason"),
            "fallback": route.get("fallback") or [],
            "attempts": trace.get("attempts") or [],
            "latency_ms": trace.get("latency_ms"),
            "usage": trace.get("usage") or {},
        })
    return calls


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, int]:
    """Tokens over the whole run. Providers that report nothing contribute nothing."""
    totals = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    for call in calls:
        for key in totals:
            value = (call.get("usage") or {}).get(key)
            if isinstance(value, (int, float)):
                totals[key] += int(value)
    totals["calls"] = len(calls)
    return totals


def build_row(run: dict[str, Any], mountain: dict[str, Any]) -> dict[str, Any]:
    """Flatten one run's view (agents.schemas.Run, model_dump(mode="json")) into a row.

    Split out from `record` so the shape is testable without a database.
    """
    advisory = run.get("advisory") or {}
    conditions = advisory.get("conditions")
    response = advisory.get("response") or {}
    model = advisory.get("model") or {}
    hazard_type = _hazard_type(run)
    calls = _llm_calls(run)

    return {
        "run_id": run["id"],
        "mountain_id": mountain.get("id"),
        "mountain_slug": run["mountain_slug"],
        "mountain_name": mountain.get("name"),
        "lat": mountain.get("lat"),
        "lon": mountain.get("lon"),
        "elevation_m": mountain.get("elevation_m"),

        "hazard_class": classify_hazard(hazard_type),
        "hazard_type": hazard_type,
        "hazard_id": run.get("hazard_id"),
        "snow_driven": is_snow_driven(conditions),

        "status": run["status"],
        "phase": run.get("phase"),
        "message": run.get("message"),
        "error": run.get("error"),
        "failed_agent": run.get("failed_agent"),
        "started_at": run["started_at"],
        "finished_at": run.get("finished_at"),
        "elapsed_s": run.get("elapsed_s"),

        "severity": run.get("severity") or advisory.get("severity"),
        "confidence": advisory.get("confidence"),
        "needs_review": run.get("needs_review"),
        "recommended_action": response.get("recommended_action"),
        "posture": response.get("posture"),
        "priority": response.get("priority"),
        "headline": response.get("headline"),
        "summary": advisory.get("summary"),

        "model_method": model.get("method") or run.get("method"),
        "model_is_stand_in": model.get("is_stand_in"),
        "model_note": model.get("note"),
        "model_max_probability": model.get("map_max"),
        "model_mean_probability": model.get("map_mean"),
        "model_share_at_high": model.get("share_at_high"),
        "model_output": Jsonb(model or {}),

        "agent_outputs": Jsonb(run.get("agents") or {}),
        "agent_verdicts": Jsonb(advisory.get("agents") or {}),
        "llm_calls": Jsonb(calls),
        "llm_usage": Jsonb(_sum_usage(calls)),

        "advisory": Jsonb(advisory) if advisory else None,
        "conditions": Jsonb(conditions) if conditions else None,
        "rain": Jsonb(run["rain"]) if run.get("rain") else None,
        "run": Jsonb(run),
    }


# Re-recording the same run (a retry, or a second _store_run for the same id) overwrites its
# row rather than piling up duplicates.
_INSERT = """
INSERT INTO previous_runs ({columns}) VALUES ({placeholders})
ON CONFLICT (run_id) DO UPDATE SET {updates}
"""


def record(run: dict[str, Any], mountain: dict[str, Any]) -> None:
    """Log one run. Fail-soft: a broken log must never break the run that produced it."""
    try:
        row = build_row(run, mountain)
        columns = list(row)
        sql = _INSERT.format(
            columns=", ".join(columns),
            placeholders=", ".join(["%s"] * len(columns)),
            updates=", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "run_id"),
        )
        with get_pool().connection() as conn:
            conn.execute(sql, [row[c] for c in columns])
    except Exception:
        logger.exception("could not log run %s to previous_runs", run.get("id"))


# --- reading it back ---------------------------------------------------------------------


def list_runs(
    limit: int = 100,
    offset: int = 0,
    slug: str | None = None,
    hazard_class: str | None = None,
    status: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """A page of history, newest first, plus the total matching rows (for the page count)."""
    where, params = ["TRUE"], []
    if slug:
        where.append("mountain_slug = %s")
        params.append(slug)
    if hazard_class:
        where.append("hazard_class = %s")
        params.append(hazard_class)
    if status:
        where.append("status = %s")
        params.append(status)
    clause = " AND ".join(where)
    with get_pool().connection() as conn:
        total = conn.execute(
            f"SELECT count(*) AS n FROM previous_runs WHERE {clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT {SUMMARY_COLUMNS} FROM previous_runs WHERE {clause}
            ORDER BY started_at DESC LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


def get_run_record(run_id: str) -> dict[str, Any] | None:
    """One history row with every payload: the agents' traces, the model's output, the advisory."""
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            SELECT {SUMMARY_COLUMNS},
                   model_note, model_mean_probability, model_output,
                   agent_outputs, advisory, conditions, rain, run
            FROM previous_runs WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


def stats() -> dict[str, Any]:
    """Counts for the history page header: runs, and how they split by tag and outcome."""
    with get_pool().connection() as conn:
        totals = conn.execute(
            """
            SELECT count(*) AS runs,
                   count(*) FILTER (WHERE status = 'done') AS done,
                   count(*) FILTER (WHERE status = 'error') AS failed,
                   count(DISTINCT mountain_slug) AS mountains
            FROM previous_runs
            """
        ).fetchone()
        by_class = conn.execute(
            "SELECT hazard_class, count(*) AS n FROM previous_runs GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    return {
        **dict(totals),
        "by_hazard_class": {row["hazard_class"]: row["n"] for row in by_class},
    }
