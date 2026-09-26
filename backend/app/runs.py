"""Analysis runs, held in the API process and keyed by run_id (step 22). No Redis: one live mountain.

POST /mountains/{slug}/analyze starts a run, or hands back the one already running. A run:

1. inserts its analysis_runs row;
2. fetches rain once and scores the step 18 map, trail risk, zone, and step 19 bypass;
3. runs the agents, five analysts at once and then the Synthesizer and the Alert Writer,
   relaying each AgentEvent to the run's stream listeners;
4. on success, renders the probability tiles, stores the trail's segment risk, saves the hazard
   with the agents' text, and sets the mountain's risk level and last_analyzed_at, all in one
   transaction;
5. stores the whole run (every agent's last event and trace, and the advisory) on its
   analysis_runs row, so GET /runs/{id}/advisory still answers after a restart.

A run that fails writes nothing from step 4, so the map keeps the last good hazard. Either way
the stream gets a final RunUpdate and closes: a listener never hangs.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.agents.pipeline import Final, Pipeline
from app.agents.providers import Provider, make_providers
from app.agents.router import Router
from app.agents.schemas import (
    Advisory,
    AgentEvent,
    AgentName,
    ProviderName,
    RainTotals,
    Run,
    RunPhase,
    RunUpdate,
)
from app.agents.tools import RunContext
from app.assessment import Assessment, assess, publish, save_hazard
from app import previous_runs
from app.db import get_pool
from app.ml.geo_susceptibility import predict_summit
from app.ml.readiness import format_missing_artifacts, setup_ready_for_analyze
from app.weather import HourlyRain, summarize, try_hourly_rain

logger = logging.getLogger(__name__)

# How the status line names the step a run failed at (design addendum, States).
STEP_NAMES: dict[AgentName, str] = {
    "terrain": "Terrain",
    "weather": "Weather",
    "trail": "Trail",
    "history": "History",
    "routes": "Route Scout",
    "synthesizer": "Synthesizer",
    "writer": "Alert Writer",
}


@dataclass
class RunState:
    id: str
    slug: str
    mountain_id: str
    mountain_name: str
    peak: tuple[float, float]
    elevation_m: int | None = None
    seed_level: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.perf_counter)
    status: str = "running"
    phase: RunPhase = "starting"
    message: str = "Starting the analysis."
    finished_at: datetime | None = None
    agents: dict[AgentName, AgentEvent] = field(default_factory=dict)
    hazard_id: str | None = None
    severity: str | None = None
    needs_review: bool | None = None
    method: str | None = None
    rain: RainTotals | None = None
    error: str | None = None
    failed_agent: AgentName | None = None
    advisory: Advisory | None = None
    listeners: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None

    def view(self) -> Run:
        elapsed = (self.finished_at or datetime.now(UTC)) - self.started_at
        return Run(
            id=self.id,
            mountain_slug=self.slug,
            status=self.status,
            phase=self.phase,
            message=self.message,
            started_at=self.started_at,
            finished_at=self.finished_at,
            elapsed_s=round(elapsed.total_seconds(), 1),
            agents=self.agents,
            hazard_id=self.hazard_id,
            severity=self.severity,
            needs_review=self.needs_review,
            method=self.method,
            rain=self.rain,
            error=self.error,
            failed_agent=self.failed_agent,
            advisory=self.advisory,
        )


class RunRegistry:
    """Every run this process has started, and the one running per mountain."""

    def __init__(self, providers: dict[ProviderName, Provider] | None = None):
        self.runs: dict[str, RunState] = {}
        self.active: dict[str, str] = {}
        self._providers = providers
        self._router: Router | None = None

    def _llm(self) -> tuple[Router, dict[ProviderName, Provider]]:
        """The providers and one router for the process, so provider health carries across runs."""
        if self._providers is None:
            self._providers = make_providers()
        if self._router is None:
            self._router = Router(self._providers)
        return self._router, self._providers

    def get(self, run_id: str) -> RunState | None:
        return self.runs.get(run_id)

    def active_run(self, slug: str) -> RunState | None:
        run_id = self.active.get(slug)
        return self.runs.get(run_id) if run_id else None

    def start(self, slug: str, mountain: dict) -> tuple[RunState, bool]:
        """A new run in the background, or the one already running. Returns (run, started)."""
        running = self.active_run(slug)
        if running is not None and running.status == "running":
            return running, False
        state = RunState(
            id=str(uuid.uuid4()), slug=slug, mountain_id=str(mountain["id"]),
            mountain_name=mountain["name"], peak=(mountain["lat"], mountain["lon"]),
            elevation_m=mountain.get("elevation_m"), seed_level=mountain.get("current_risk_level"),
        )
        self.runs[state.id] = state
        self.active[slug] = state.id
        state.task = asyncio.create_task(self._execute(state), name=f"run-{state.id}")
        return state, True

    # --- listeners -------------------------------------------------------------------------

    def subscribe(self, state: RunState) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        state.listeners.add(queue)
        return queue

    @staticmethod
    def unsubscribe(state: RunState, queue: asyncio.Queue) -> None:
        state.listeners.discard(queue)

    @staticmethod
    def _broadcast(state: RunState, message: dict) -> None:
        for queue in list(state.listeners):
            queue.put_nowait(message)

    def _update(self, state: RunState) -> None:
        self._broadcast(state, RunUpdate(run=state.view()).model_dump(mode="json"))

    # --- the run ---------------------------------------------------------------------------

    async def _phase(self, state: RunState, phase: RunPhase, message: str) -> None:
        state.phase, state.message = phase, message
        self._update(state)

    async def _on_event(self, state: RunState, event: AgentEvent) -> None:
        state.agents[event.agent] = event
        self._broadcast(state, event.model_dump(mode="json"))

    async def _execute(self, state: RunState) -> None:
        try:
            await asyncio.to_thread(_insert_run, state)
            if not await asyncio.to_thread(_has_mile_segments, state.slug):
                await self._execute_location(state)
                return
            if not setup_ready_for_analyze():
                await self._fail(
                    state,
                    "Run failed before scoring: local ML artifacts are missing.",
                    format_missing_artifacts(
                        FileNotFoundError("ml/artifacts/susceptibility.tif is missing")
                    ),
                    None,
                )
                return
            await self._phase(state, "scoring", "Scoring the next 72 hours of rain against the terrain.")
            rain, rain_error = await asyncio.to_thread(try_hourly_rain, *state.peak)
            if rain is not None:
                state.rain = _rain_totals(rain)
            assessment = await asyncio.to_thread(_assess, state.slug, rain)
            state.method = assessment.method

            await self._phase(state, "agents",
                              "Five analysts are reading the model's map at once, then one synthesizer decides.")
            router, providers = self._llm()
            ctx = RunContext(run_id=state.id, slug=state.slug, mountain=state.mountain_name, peak=state.peak,
                             assessment=assessment, rain=rain, rain_error=rain_error, started=state.started)
            result = await Pipeline(ctx, router, providers, lambda event: self._on_event(state, event)).run()
            if result.status != "done":
                step = STEP_NAMES.get(result.failed_agent, "agent")
                await self._fail(state, f"Run failed at the {step} step.", result.error, result.failed_agent)
                return

            await self._phase(state, "saving", "Saving the hazard, the heat map, and the trail's risk.")
            state.hazard_id = await asyncio.to_thread(_commit, state, assessment, result.final)
            state.severity, state.needs_review = result.final.severity, result.final.needs_review
            # The advisory is the run's whole conclusion, and it rides on every later view of the
            # run: the stream, GET /runs/{id}, and the stored row.
            state.advisory = result.final.advisory
            await self._finish(state, result.final)
            _log_agent_latencies(state, result)
        except FileNotFoundError as exc:
            logger.exception("run %s failed during scoring (missing file)", state.id)
            await self._fail(
                state,
                "Run failed while scoring the map.",
                format_missing_artifacts(exc),
                None,
            )
        except Exception as exc:  # a run must always end, and say why
            logger.exception("run %s failed at phase=%s", state.id, state.phase)
            detail = format_missing_artifacts(exc) if isinstance(exc, OSError) else f"{type(exc).__name__}: {exc}"
            await self._fail(state, "Run failed before the agents finished.", detail, None)
        finally:
            if self.active.get(state.slug) == state.id:
                del self.active[state.slug]

    async def _execute_location(self, state: RunState) -> None:
        """Agents for a summit with no trail geometry: location, the cell classifier, and weather."""
        from app.agents.location_pipeline import LocationPipeline

        try:
            await self._phase(state, "scoring", "Reading weather and the risk model at this summit.")
            rain, rain_error = await asyncio.to_thread(try_hourly_rain, state.peak[0], state.peak[1])
            if rain is not None:
                state.rain = _rain_totals(rain)
            geo = await asyncio.to_thread(predict_summit, state.slug, state.peak[0], state.peak[1])
            state.method = geo["method"] if geo.get("available") else "location cell classification"
            await self._phase(state, "agents", "Agents are reading this summit's location, risk, and weather.")
            router, providers = self._llm()
            ctx = RunContext(
                run_id=state.id, slug=state.slug, mountain=state.mountain_name, peak=state.peak,
                assessment=None, rain=rain, rain_error=rain_error, started=state.started,
                elevation_m=state.elevation_m, seed_level=state.seed_level,
            )
            result = await LocationPipeline(ctx, router, providers, lambda event: self._on_event(state, event)).run()
            if result.status != "done":
                step = STEP_NAMES.get(result.failed_agent, "agent")
                await self._fail(state, f"Run failed at the {step} step.", result.error, result.failed_agent)
                return
            await self._phase(state, "saving", "Saving this summit's risk level.")
            await asyncio.to_thread(_save_level, state, result.final.severity)
            state.severity, state.needs_review = result.final.severity, result.final.needs_review
            state.advisory = result.final.advisory
            await self._finish(state, result.final)
            _log_agent_latencies(state, result)
        except Exception as exc:
            logger.exception("location run %s failed", state.id)
            await self._fail(state, "Run failed before the agents finished.", f"{type(exc).__name__}: {exc}", None)

    async def _finish(self, state: RunState, final: Final) -> None:
        state.status, state.phase, state.finished_at = "done", "finished", datetime.now(UTC)
        seconds = (state.finished_at - state.started_at).total_seconds()
        state.message = f"Finished in {seconds:.0f} s."
        if final.needs_review:
            state.message += " Agents disagree on severity, so this is an advisory."
        await asyncio.to_thread(_store_run, state)
        self._update(state)

    async def _fail(self, state: RunState, message: str, error: str | None, agent: AgentName | None) -> None:
        state.status, state.phase, state.finished_at = "error", "finished", datetime.now(UTC)
        state.message, state.error, state.failed_agent = message, error, agent
        await asyncio.to_thread(_store_run, state)
        self._update(state)


# --- database work, run in worker threads ------------------------------------------------------


def _log_agent_latencies(state: RunState, result) -> None:
    """One line per finished run: where time went, for demo tuning."""
    parts: list[str] = []
    for name in ("terrain", "weather", "trail", "history", "routes", "synthesizer", "writer"):
        run = result.runs.get(name)
        if run and run.trace and run.trace.latency_ms is not None:
            provider = run.trace.route.provider if run.trace.route else "?"
            parts.append(f"{name}={run.trace.latency_ms}ms({provider})")
    if parts:
        elapsed = (state.finished_at or datetime.now(UTC)) - state.started_at
        logger.info("run %s done in %.1fs: %s", state.id, elapsed.total_seconds(), ", ".join(parts))


def _rain_totals(rain: HourlyRain) -> RainTotals:
    totals = summarize(rain)
    return RainTotals(source=totals.source, as_of=totals.as_of, past_72h_mm=totals.past_72h_mm,
                      next_24h_mm=totals.next_24h_mm)


def _insert_run(state: RunState) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO analysis_runs (id, mountain_id, status, started_at) VALUES (%s, %s, 'running', %s)",
            (state.id, state.mountain_id, state.started_at),
        )


def _has_mile_segments(slug: str) -> bool:
    """True when this mountain has a trail cut into mile segments, which is what the Rainier pipeline scores."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM trail_segments s
            JOIN trails t ON t.id = s.trail_id
            JOIN mountains m ON m.id = t.mountain_id
            WHERE m.slug = %s
            LIMIT 1
            """,
            (slug,),
        ).fetchone()
    return row is not None


def _save_level(state: RunState, severity: str) -> None:
    """Record the run's level on the mountain. A location run has no tiles or hazard polygon to save."""
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE mountains SET current_risk_level = %s, last_analyzed_at = now() WHERE id = %s",
            (severity, state.mountain_id),
        )


def _assess(slug: str, rain: HourlyRain | None) -> Assessment:
    with get_pool().connection() as conn:
        return assess(conn, slug, rain)


def _commit(state: RunState, assessment: Assessment, final: Final) -> str | None:
    """Tiles, segment risk, the hazard, and the mountain's level, together. Returns the hazard id."""
    with get_pool().connection() as conn, conn.transaction():
        publish(conn, assessment)
        hazard_id = None
        if assessment.zone is not None:
            hazard_id = save_hazard(
                conn, assessment, run_id=state.id, hazard_type=final.hazard_type, severity=final.severity,
                confidence=final.confidence, drivers=final.drivers, what=final.what, why=final.why,
                how_to_avoid=final.how_to_avoid, needs_review=final.needs_review,
            )
        conn.execute(
            "UPDATE mountains SET current_risk_level = %s, last_analyzed_at = now() WHERE id = %s",
            (final.severity, state.mountain_id),
        )
    return hazard_id


def _store_run(state: RunState) -> None:
    """The run's final view on its row, so GET /runs/{id} still answers after a restart.

    Then log the same view to previous_runs, which is the /history page's table. Both writes
    are fail-soft: the run's own outcome matters more than its record.
    """
    view = state.view().model_dump(mode="json")
    try:
        with get_pool().connection() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status = %s, finished_at = %s, agent_outputs = %s WHERE id = %s",
                (state.status, state.finished_at, Jsonb({"run": view}), state.id),
            )
    except Exception:  # the run's own outcome matters more than its record
        logger.exception("could not store run %s", state.id)
    previous_runs.record(view, {
        "id": state.mountain_id,
        "name": state.mountain_name,
        "lat": state.peak[0],
        "lon": state.peak[1],
        "elevation_m": state.elevation_m,
    })


def load_run(run_id: str) -> Run | None:
    """A finished run from the database, for runs this process did not start."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.status, r.started_at, r.finished_at, r.agent_outputs, m.slug
            FROM analysis_runs r JOIN mountains m ON m.id = r.mountain_id WHERE r.id = %s
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    stored = (row["agent_outputs"] or {}).get("run")
    if stored:
        return Run.model_validate(stored)
    # A run whose process ended before it finished: it has no stored view.
    return Run(id=str(row["id"]), mountain_slug=row["slug"], status="error", phase="finished",
               message="This run stopped when the API restarted.", started_at=row["started_at"],
               finished_at=row["finished_at"], elapsed_s=None, agents={}, hazard_id=None, severity=None,
               needs_review=None, method=None, rain=None, error="The API process ended during the run.",
               failed_agent=None)


def latest_advisory(slug: str) -> Advisory | None:
    """The newest advisory stored for a mountain, or None when no run has finished with one.

    Runs this process started are in memory, but a restart, a second worker, or a demo reload
    would lose them. The advisory rides on the run's stored view, so it survives all three.
    """
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT r.agent_outputs
            FROM analysis_runs r JOIN mountains m ON m.id = r.mountain_id
            WHERE m.slug = %s AND r.status = 'done'
            ORDER BY r.finished_at DESC NULLS LAST, r.started_at DESC
            LIMIT 5
            """,
            (slug,),
        ).fetchall()
    for row in rows:
        stored = ((row["agent_outputs"] or {}).get("run") or {}).get("advisory")
        if stored:
            return Advisory.model_validate(stored)
    return None


registry = RunRegistry()
