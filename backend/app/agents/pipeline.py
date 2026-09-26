"""The agent pipeline: five analysts at once, then one synthesizer, then the copy.

    terrain ─┐
    weather ─┤
    trail   ─┼─▶ synthesizer ─▶ writer
    history ─┤
    routes  ─┘

The five analysts fan out together in a single asyncio.gather. None of them reads another's
answer, so none of them waits: the run costs one analyst's latency, not five. Each reads the same
ML prediction as its source of truth (tools.get_model_prediction) and adds what the model could
not see: the ground under the zone, the rain around it, the miles hikers walk, the landslide
record, and the other 66 trails on the mountain.

The Risk Synthesizer is the only agent that sees all five, and the only one that decides
anything. It returns the run's whole conclusion in one object: the final severity and action,
three routes to keep hikers off, three that are safe today, and the response the park should
mount, from "put it in the newsletter" to "get everyone off the mountain". The Alert Writer then
turns that decision into the ranger and hiker copy; it writes, it does not decide.

For each agent the router picks a provider, the agent's tools gather facts, and one model call
returns JSON that must pass the agent's schema and checks. An AgentEvent goes out when each agent
starts and when it finishes or fails, with its full trace: the route, the tool calls, every
attempt, the model's reasoning, and what the code changed.

A call that fails is retried once on the same provider when the failure is temporary, and an
answer that fails a check is sent back once with the problems listed. After that the router's
fallback provider gets the same two chances. An agent fails only when both providers do.

Code, not a model, decides these:
- confidence: the weighted average of the analysts' confidence (CONFIDENCE_WEIGHTS);
- needs_review: set when two analysts' severities sit two or more levels apart, which turns the
  ranger alert into an advisory;
- the Synthesizer's guard rails (app/agents/advisory.py): its severity stays within the analysts'
  range; an advisory or a low or moderate level recommends "monitor", never "close"; every route
  it names must be one the code shortlisted from the scored catalog; and the ranger posture,
  priority, and channels have to match the severity the run actually reached.

Run once from backend/ against the local database:
    python -m app.agents.pipeline [--fixture-rain]
"""

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from app.assessment import (
    HAZARD_WORDS,
    Assessment,
    describe,
    mile_text,
    signed_feet,
    signed_miles,
)
from app.history import historical_events
from app.risk import RiskLevel, level_index, level_spread
from app.trailscan import TrailScore, relative_only, resolve
from app.weather import summarize

from . import advisory as guards
from .prompts import REPAIR, SYSTEM_PROMPTS
from .providers import LLMRequest, LLMResult, Provider, ProviderError, llm_schema
from .router import NoProviderError, Router, Signals
from .schemas import (
    AGENT_LABELS,
    AGENT_ORDER,
    AGENT_OUTPUTS,
    ANALYSTS,
    Advisory,
    AdvisoryAlert,
    AdvisoryConditions,
    AdvisoryHazard,
    AdvisoryModel,
    AdvisoryResponse,
    AdvisoryRoute,
    AgentEvent,
    AgentName,
    AgentOutput,
    AgentTrace,
    AgentVerdict,
    AlertDraft,
    Attempt,
    HistoryReport,
    ProviderName,
    RouteScan,
    SynthesisReport,
    TerrainReport,
    TrailReport,
    WeatherReport,
)
from .tools import MOUNTAIN_HISTORY_RADIUS_KM, RunContext, ToolError, call_tool, threshold_mm

# How much each analyst's confidence counts toward the final one. Terrain is the most direct
# evidence of where ground can fail; the weather is one reading for the whole box; the trail
# report restates them against the miles hikers walk; the record and the wider network are
# context, so they weigh least. The weights are fixed here, not chosen by a model.
CONFIDENCE_WEIGHTS: dict[AgentName, float] = {
    "terrain": 0.30, "weather": 0.25, "trail": 0.20, "routes": 0.15, "history": 0.10,
}
REVIEW_SPREAD = 2  # analysts this many levels apart put the alert out as an advisory
HIKER_MAX_WORDS = 25
MODEL_WORDS = ("probability", "confidence", "model", "susceptibility")
RETRY_PAUSE_S = 1.0
PLACE_MAX_CHARS = 60

Emit = Callable[[AgentEvent], Awaitable[None]]


class AgentFailed(Exception):
    """No provider returned an answer that passed the agent's checks."""


@dataclass
class AgentRun:
    agent: AgentName
    output: AgentOutput | None = None
    payload: dict = field(default_factory=dict)
    trace: AgentTrace | None = None
    error: str | None = None


@dataclass
class Final:
    """The run's conclusion: what the hazard row, the alert, and the hiker card carry."""

    hazard_type: str
    severity: RiskLevel
    confidence: float
    needs_review: bool
    recommended_action: str
    summary: str
    drivers: list[str]
    ranger_title: str
    ranger_body: str
    hiker: str
    what: str
    why: str
    how_to_avoid: str
    # The run's whole conclusion: routes, response, analysis. Always set on a finished run.
    advisory: Advisory | None = None


@dataclass
class PipelineResult:
    status: str  # "done" or "error"
    runs: dict[AgentName, AgentRun]
    events: list[AgentEvent]
    final: Final | None = None
    failed_agent: AgentName | None = None
    error: str | None = None


def parse_json(text: str) -> dict:
    """The JSON object in a model's answer, tolerating code fences around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("no JSON object in the answer", text, 0)
    return json.loads(text[start:end + 1])


def validation_problems(error: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}" for e in error.errors()[:6]]


def weighted_confidence(confidences: Mapping[AgentName, float]) -> float:
    total = sum(CONFIDENCE_WEIGHTS[a] for a in confidences)
    return round(sum(confidences[a] * CONFIDENCE_WEIGHTS[a] for a in confidences) / total, 2)


def ranger_line(hazard_type: str, severity: RiskLevel, place: str, trail: str, start: float | None,
                end: float | None, confidence: float, needs_review: bool) -> str:
    """The design addendum's ranger line: '<Hazard> risk <LEVEL>. <Place>, <trail> mile a to b. Confidence 0.00.'"""
    place = place.strip().rstrip(".")[:PLACE_MAX_CHARS]
    place = place[:1].upper() + place[1:]
    where = f"{place}, {trail} {mile_text(start, end)}" if start is not None else f"{trail}, no mile at high"
    line = f"{HAZARD_WORDS.get(hazard_type, 'Landslide')} risk {severity.upper()}. {where}. Confidence {confidence:.2f}."
    return f"Advisory. {line} Confirm on site before closing." if needs_review else line


def writer_problems(draft: AlertDraft, trail: str, bypass: str | None, flagged: bool, needs_review: bool) -> list[str]:
    """The copy rules the Alert Writer's text must meet (design addendum, Copy)."""
    problems = []
    words = len(draft.hiker.split())
    if words > HIKER_MAX_WORDS:
        problems.append(f"hiker has {words} words; the limit is {HIKER_MAX_WORDS}.")
    if re.search(r"\d", draft.hiker):
        problems.append("hiker contains a number; it must have none.")
    banned = [w for w in MODEL_WORDS if re.search(rf"\b{w}\b", draft.hiker, re.IGNORECASE)]
    if banned:
        problems.append(f"hiker uses {', '.join(banned)}, which hikers should not see.")
    if flagged:
        if trail.lower() not in draft.ranger_body.lower():
            problems.append(f"ranger_body must name the {trail}.")
        if trail.lower() not in draft.what.lower():
            problems.append(f"what must name the {trail}.")
        if bypass:
            if bypass.lower() not in draft.hiker.lower():
                problems.append(f"hiker must name the bypass, the {bypass}.")
            if bypass.lower() not in draft.how_to_avoid.lower():
                problems.append(f"how_to_avoid must name the bypass, the {bypass}.")
        elif "turn back" not in draft.hiker.lower():
            problems.append("hiker must tell hikers to turn back: there is no bypass.")
    if needs_review:
        if not draft.ranger_body.startswith("Advisory."):
            problems.append('ranger_body must start with "Advisory." because the reports disagree.')
        if not draft.ranger_body.rstrip().endswith("Confirm on site before closing."):
            problems.append('ranger_body must end with "Confirm on site before closing."')
    return problems


class Pipeline:
    def __init__(self, ctx: RunContext, router: Router, providers: Mapping[ProviderName, Provider], emit: Emit):
        self.ctx = ctx
        self.router = router
        self.providers = providers
        self.emit = emit
        self.events: list[AgentEvent] = []
        self.runs: dict[AgentName, AgentRun] = {}

    # --- the run ---------------------------------------------------------------------------

    async def run(self) -> PipelineResult:
        """The five analysts together, then the Synthesizer, then the Writer.

        The gather is the whole point: five model calls are in flight at once, so the analyst
        stage costs the slowest one rather than the sum. An analyst that fails does not stop the
        others, and the run ends at the first failure in panel order once they are all back.
        """
        await asyncio.gather(*(getattr(self, agent)() for agent in ANALYSTS))
        failed = self._first_failure()
        if failed is None:
            await self.synthesizer()
            failed = self._first_failure()
        if failed is None:
            await self.writer()
            failed = self._first_failure()
        if failed is not None:
            return PipelineResult("error", self.runs, self.events, failed_agent=failed, error=self.runs[failed].error)
        return PipelineResult("done", self.runs, self.events, final=self._final())

    def _first_failure(self) -> AgentName | None:
        return next((a for a in AGENT_ORDER if a in self.runs and self.runs[a].error), None)

    # --- one agent -------------------------------------------------------------------------

    async def _event(self, agent: AgentName, status: str, summary: str, payload: dict | None = None,
                     trace: AgentTrace | None = None) -> None:
        event = AgentEvent(run_id=self.ctx.run_id, agent=agent, status=status, summary=summary,
                           payload=payload or {}, trace=trace.model_copy(deep=True) if trace else None)
        self.events.append(event)
        await self.emit(event)

    async def _call(self, agent: AgentName, *, signals: Signals, running: str, tools: list[tuple[str, dict]],
                    context: dict, check: Callable[[AgentOutput], list[str]] | None = None,
                    soft_check: bool = False, system: str | None = None,
                    output_model: type[AgentOutput] | None = None) -> tuple[AgentRun, list[str]]:
        """Route, gather facts, ask the model, and validate. Returns the run and any checks still failing."""
        run = AgentRun(agent)
        self.runs[agent] = run
        signals.elapsed_s = self.ctx.elapsed_s
        try:
            decision = self.router.route(agent, signals)
        except NoProviderError as exc:
            run.error = str(exc)
            await self._event(agent, "error", f"Failed: {exc}", {"error": str(exc)})
            return run, []
        trace = AgentTrace(route=decision, started_at=datetime.now(UTC))
        run.trace = trace
        await self._event(agent, "running", running, trace=trace)
        remaining: list[str] = []
        model = output_model or AGENT_OUTPUTS[agent]
        try:
            trace.tools = [await asyncio.to_thread(call_tool, self.ctx, name, **args) for name, args in tools]
            request = LLMRequest(
                system=system or SYSTEM_PROMPTS[agent],
                user=self._message(agent, trace, context),
                schema=llm_schema(model),
                schema_name=f"{agent}_report",
            )
            output, result, remaining = await self._ask(agent, decision.provider, decision.fallback, request,
                                                        trace, check, soft_check, output_model=model)
        except (ToolError, AgentFailed) as exc:
            run.error = str(exc)
            self._finish(trace)
            await self._event(agent, "error", f"Failed: {exc}", {"error": str(exc)}, trace)
            return run, []
        run.output = output
        trace.thoughts = result.thoughts
        trace.reasoning = list(output.reasoning)
        trace.output = output.model_dump()
        trace.usage = result.usage
        return run, remaining

    async def _done(self, run: AgentRun, summary: str, payload: dict) -> None:
        run.payload = payload
        self._finish(run.trace)
        await self._event(run.agent, "done", summary, payload, run.trace)

    @staticmethod
    def _finish(trace: AgentTrace | None) -> None:
        if trace is None:
            return
        trace.finished_at = datetime.now(UTC)
        if trace.started_at:
            trace.latency_ms = round((trace.finished_at - trace.started_at).total_seconds() * 1000)

    @staticmethod
    def _tool(run: AgentRun, name: str) -> dict | None:
        """One tool's result from an agent's trace, by name rather than by position."""
        if run.trace is None:
            return None
        return next((call.result for call in run.trace.tools if call.name == name), None)

    def _message(self, agent: AgentName, trace: AgentTrace, context: dict) -> str:
        parts = [f"{self.ctx.mountain}, run {self.ctx.run_id}. You are the {AGENT_LABELS[agent]}."]
        if trace.tools:
            parts.append("Tool results:")
            for call in trace.tools:
                parts.append(f"{call.name}({json.dumps(call.args)}) returned:\n```json\n"
                             f"{json.dumps(call.result, indent=1, default=str)}\n```")
        for title, value in context.items():
            parts.append(f"{title}:\n```json\n{json.dumps(value, indent=1, default=str)}\n```")
        parts.append("Answer with the JSON object only.")
        return "\n\n".join(parts)

    async def _ask(self, agent: AgentName, first: ProviderName, fallback: list[ProviderName], request: LLMRequest,
                   trace: AgentTrace, check, soft_check: bool,
                   output_model: type[AgentOutput] | None = None) -> tuple[AgentOutput, LLMResult, list[str]]:
        """Two tries per provider, the router's pick first. See the module docstring."""
        model = output_model or AGENT_OUTPUTS[agent]
        best: tuple[AgentOutput, LLMResult, list[str]] | None = None  # schema-valid, checks failing
        last_error = "no provider was tried"
        for name in [first, *fallback]:
            provider = self.providers[name]
            ask, repair = request, False
            for attempt in range(2):
                called = time.perf_counter()
                try:
                    result = await provider.generate(ask)
                except ProviderError as exc:
                    self.router.record_failure(name)
                    last_error = f"{provider.label}: {exc}"
                    trace.attempts.append(Attempt(provider=name, model=provider.model, ok=False,
                                                  latency_ms=round((time.perf_counter() - called) * 1000),
                                                  error=str(exc), repair=repair))
                    if exc.retryable and attempt == 0:
                        await asyncio.sleep(RETRY_PAUSE_S)
                        continue
                    break
                try:
                    output = model.model_validate(parse_json(result.text))
                    problems = check(output) if check else []
                except json.JSONDecodeError:
                    output, problems = None, ["The answer was not a JSON object."]
                except ValidationError as exc:
                    output, problems = None, validation_problems(exc)
                trace.attempts.append(Attempt(provider=name, model=result.model, ok=not problems,
                                              latency_ms=result.latency_ms, error="; ".join(problems) or None,
                                              repair=repair))
                if not problems:
                    self.router.record_success(name)
                    return output, result, []
                if output is not None:
                    best = (output, result, problems)
                last_error = f"{provider.label}: {'; '.join(problems)}"
                ask = LLMRequest(system=request.system,
                                 user=f"{request.user}\n\nYour last answer was:\n{result.text}\n\n"
                                      + REPAIR.format(problems="\n".join(f"- {p}" for p in problems)),
                                 schema=request.schema, schema_name=request.schema_name)
                repair = True
        if soft_check and best is not None:
            return best
        raise AgentFailed(f"No provider returned a usable answer. Last: {last_error}")

    # --- the five agents -------------------------------------------------------------------

    @property
    def a(self) -> Assessment:
        return self.ctx.assessment

    @property
    def scores(self) -> list[TrailScore]:
        return self.a.trail_scores

    def _prediction(self) -> tuple[str, dict]:
        """The tool call every agent makes first: the ML model's output as the source of truth."""
        return ("get_model_prediction", {"mountain": self.ctx.slug})

    async def terrain(self) -> AgentRun:
        zone = self.a.zone
        tools = [self._prediction(), ("get_raster_summary", {"mountain": self.ctx.slug})]
        if zone is not None:
            tools.append(("get_historical_events", {"lat": zone.centroid[1], "lon": zone.centroid[0], "radius_km": 5.0}))
        run, _ = await self._call("terrain", signals=Signals(zone_peak=zone.max_probability if zone else None),
                                  running="Reading the hazard zone on the 72-hour map.", tools=tools, context={})
        if run.error:
            return run
        out: TerrainReport = run.output
        drivers, dropped = list(out.drivers), []
        history = self._tool(run, "get_historical_events") or {"events": []}
        for driver in list(drivers):
            if driver in ("recent_rain", "forecast_rain") or (driver == "past_landslides" and not history["events"]):
                drivers.remove(driver)
                dropped.append(driver)
        if dropped:
            reason = "rain is the Weather Analyst's call" if set(dropped) <= {"recent_rain", "forecast_rain"} else \
                "the facts do not support them"
            run.trace.checks.append(f"Dropped {', '.join(dropped)} from the drivers: {reason}.")
        if not drivers:
            drivers = list(zone.drivers_hint[:2]) if zone and zone.drivers_hint else ["slope_angle"]
            run.trace.checks.append(f"No driver was left, so the zone's terrain hints stand in: {', '.join(drivers)}.")
        peak = zone.max_probability if zone else self.a.map_summary["max"]
        run.trace.checks.append(f"max_probability {peak} comes from the map, not the model.")
        payload = {
            "hazard_zone": {"id": "hz_001", "type": out.type, "severity": out.severity, "max_probability": peak,
                            "drivers": drivers, "confidence": out.confidence, "place": out.place,
                            "notes": out.notes},
            "method": self.a.method,
        }
        where = f" {out.place[:1].lower()}{out.place[1:]}" if out.place else ""
        await self._done(run, f"{HAZARD_WORDS[out.type]} zone{where.rstrip('.')}. Severity {out.severity}, "
                              f"peak {peak:.2f}.", payload)
        return run

    async def weather(self) -> AgentRun:
        ratio = None
        if self.ctx.rain is not None:
            rain = summarize(self.ctx.rain)
            ratio = max(rain.past_72h_mm, rain.next_72h_mm) / threshold_mm(72)
        lat, lon = self.ctx.peak
        run, _ = await self._call("weather", signals=Signals(rain_ratio=ratio),
                                  running="Checking past and forecast rain at the trail zone.",
                                  tools=[self._prediction(), ("get_weather", {"lat": lat, "lon": lon})],
                                  context={})
        if run.error:
            return run
        out: WeatherReport = run.output
        facts = self._tool(run, "get_weather")
        payload = {
            "modifier": out.modifier,
            "severity": out.severity,
            "confidence": out.confidence,
            "rain_past_72h_mm": facts["mm"]["past_72h"],
            "rain_next_24h_mm": facts["mm"]["next_24h"],
            "rain_source": facts["source"],
            "conditions": facts["conditions"],
            "note": out.note,
        }
        run.trace.checks.append("Rain totals and conditions in the payload come from the Open-Meteo facts, "
                                "not the model.")
        trend = {"worse": "The zone is getting worse.", "stable": "The zone holds steady.",
                 "better": "The zone is easing."}[out.modifier]
        await self._done(run, f"{facts['mm']['past_72h']:.0f} mm in the past 72 hours and "
                              f"{facts['mm']['next_24h']:.0f} mm in the next 24. {trend}", payload)
        return run

    async def trail(self) -> AgentRun:
        flagged, bypass = self.a.flagged, self.a.bypass
        signals = Signals(bypass_exists=(bypass is not None) if flagged else None,
                          bypass_level=bypass.level if bypass else None)
        run, _ = await self._call("trail", signals=signals, running="Checking the flagged miles and the bypass.",
                                  tools=[self._prediction(),
                                         ("get_trail_segments", {"mountain": self.ctx.slug})], context={})
        if run.error:
            return run
        out: TrailReport = run.output
        trail = self.a.trail.name
        payload = {
            "trail_name": trail,
            "start_mile": flagged.start_mile if flagged else None,
            "end_mile": flagged.end_mile if flagged else None,
            "severity": out.severity,
            "confidence": out.confidence,
            "bypass": None if bypass is None else {
                "name": bypass.name,
                "added_km": bypass.added_km,
                "added_elevation_m": bypass.added_elevation_m,
                "leaves_at_mile": bypass.leaves_at_mile,
                "rejoins_at_mile": bypass.rejoins_at_mile,
            },
            "note": out.note,
        }
        run.trace.checks.append("The flagged miles and the bypass come from the map and the trail network, not the model: it only explains them.")
        if flagged is None:
            summary = f"No mile of the {trail} reaches high."
        elif bypass is None:
            summary = f"{trail} {mile_text(flagged.start_mile, flagged.end_mile)} crosses the zone. No bypass: " \
                      f"turn back before mile {flagged.start_mile:.1f}."
        else:
            summary = f"{trail} {mile_text(flagged.start_mile, flagged.end_mile)} crosses the zone. " \
                      f"Bypass: {bypass.name}."
        await self._done(run, summary[:1].upper() + summary[1:], payload)
        return run

    async def history(self) -> AgentRun:
        """What the landslide catalog says. The model has never seen a past slide; this agent has."""
        lat, lon = self.ctx.peak
        if self.a.zone is not None:
            lon, lat = self.a.zone.centroid
        tools = [self._prediction(),
                 ("get_historical_events", {"lat": lat, "lon": lon, "radius_km": MOUNTAIN_HISTORY_RADIUS_KM})]
        # The router needs the event count before the call, so the tool's own radius is counted here.
        count = len(historical_events(self.ctx.slug))
        run, _ = await self._call("history", signals=Signals(analog_count=count),
                                  running="Reading the landslide record near the zone.", tools=tools, context={})
        if run.error:
            return run
        out: HistoryReport = run.output
        facts = self._tool(run, "get_historical_events") or {"events": []}
        events = facts.get("events", [])
        nearest = events[0] if events else None
        if not events and out.precedent != "none":
            run.trace.checks.append(f"Set the precedent to none from {out.precedent}: the catalog returned no "
                                    "event within the search radius.")
            out = out.model_copy(update={"precedent": "none"})
        payload = {
            "precedent": out.precedent,
            "severity": out.severity,
            "confidence": out.confidence,
            "events_within_radius": len(events),
            "search_radius_km": facts.get("radius_km", MOUNTAIN_HISTORY_RADIUS_KM),
            "nearest_event": nearest,
            "catalog_note": facts.get("catalog_note"),
            "note": out.note,
        }
        run.trace.checks.append("The event count and the nearest event come from the catalog, not the model.")
        if not events:
            run.trace.checks.append("An empty catalog is not evidence of safety: it is usually evidence that "
                                    "nobody recorded a slide here.")
            summary = "No catalog landslide near the zone. Absence of record, not absence of risk."
        else:
            summary = (f"{len(events)} past slide{'s' if len(events) != 1 else ''} within "
                       f"{payload['search_radius_km']:.0f} km. Precedent {out.precedent}.")
        await self._done(run, summary, payload)
        return run

    async def routes(self) -> AgentRun:
        """Every mapped trail, not just the hero trail: where else the risk falls, and what stays clear."""
        clear = sum(1 for s in self.scores if s.recommendable)
        run, _ = await self._call("routes", signals=Signals(clear_routes=clear),
                                  running="Scoring every trail on the mountain, not just the hero trail.",
                                  tools=[self._prediction(),
                                         ("get_trail_catalog", {"mountain": self.ctx.slug})], context={})
        if run.error:
            return run
        out: RouteScan = run.output
        comparative = relative_only(self.scores, needed=3, limit=guards.SAFE_POOL)

        def named(notes, kept: list[dict], dropped: list[str]) -> None:
            for note in notes:
                match = resolve(self.scores, note.trail)
                if match is None:
                    dropped.append(note.trail)
                else:
                    kept.append({**match.to_json(), "note": note.note})

        exposed: list[dict] = []
        clear_routes: list[dict] = []
        dropped: list[str] = []
        named(out.exposed, exposed, dropped)
        named(out.clear, clear_routes, dropped)
        if dropped:
            run.trace.checks.append(f"Dropped {', '.join(repr(name) for name in dropped)}: not a trail in the "
                                    "route catalog, so the map says nothing about it.")
        if not exposed:
            exposed = [s.to_json() for s in guards.avoid_pool(self.scores)[:3]]
            run.trace.checks.append("No named trail survived, so the catalog's own worst three stand in.")
        if not clear_routes:
            clear_routes = [s.to_json() for s in guards.safe_pool(self.scores)[:3]]
            run.trace.checks.append("No named trail survived, so the catalog's own cleanest three stand in.")
        payload = {
            "severity": out.severity,
            "confidence": out.confidence,
            "exposed": exposed,
            "clear": clear_routes,
            "trails_scored": len(self.scores),
            "clear_of_the_safe_ceiling": clear,
            "safety_is_relative": comparative,
            "note": out.note,
        }
        run.trace.checks.append("Every probability, mile, and level here is the map's, sampled along each trail: "
                                "the agent chose which trails to name, not what they score.")
        if comparative:
            run.trace.checks.append(f"Only {clear} trail{'s' if clear != 1 else ''} clear the safe ceiling, so the "
                                    "clear list is the least exposed ground rather than safe ground.")
        worst = exposed[0]["trail"] if exposed else "none"
        await self._done(run, f"{len(self.scores)} trails scored. Worst: the {worst}. "
                              f"{clear} clear the safe ceiling.", payload)
        return run

    async def synthesizer(self) -> AgentRun:
        """The one agent that decides: severity, action, six routes, and the park's response."""
        reports = {agent: self.runs[agent].output for agent in ANALYSTS}
        levels = tuple(report.severity for report in reports.values())
        confidence = weighted_confidence({agent: report.confidence for agent, report in reports.items()})
        spread = level_spread(levels)
        needs_review = spread >= REVIEW_SPREAD
        avoid_pool = guards.avoid_pool(self.scores)
        safe_pool = guards.safe_pool(self.scores)
        comparative = relative_only(self.scores, needed=3, limit=guards.SAFE_POOL)
        bypass = self.a.bypass
        context = {
            f"{AGENT_LABELS[agent]}'s report": self.runs[agent].payload for agent in ANALYSTS
        }
        context["Routes to avoid: the shortlist you must pick three from"] = [s.to_json() for s in avoid_pool]
        context["Safe route candidates: the shortlist you must pick three from"] = {
            "safety_is_relative": comparative,
            "note": ("No trail on the mountain clears the safe ceiling today, so these are the least exposed "
                     "ground, not safe ground. Every caution must say so."
                     if comparative else "These trails clear the safe ceiling today."),
            "trails": [s.to_json() for s in safe_pool],
        }
        context["The named bypass around the flagged miles"] = None if bypass is None else {
            "name": bypass.name, "leaves_at_mile": bypass.leaves_at_mile,
            "rejoins_at_mile": bypass.rejoins_at_mile, "worst_ground_level": bypass.level,
        }
        context["Computed by code"] = {
            "final_confidence": confidence, "severity_spread_levels": spread, "needs_review": needs_review,
            "weights": CONFIDENCE_WEIGHTS, "analyst_severities": dict(zip(ANALYSTS, levels, strict=True)),
        }

        def check(report: SynthesisReport) -> list[str]:
            return guards.route_problems(report.avoid, report.safe, self.scores)

        run, remaining = await self._call(
            "synthesizer", signals=Signals(report_levels=levels),
            running="Weighing five reports into one call, six routes, and a response.", tools=[],
            context=context, check=check, soft_check=True)
        if run.error:
            return run
        out: SynthesisReport = run.output

        terms = " + ".join(f"{reports[a].confidence:.2f} x {CONFIDENCE_WEIGHTS[a]:.2f}" for a in reports)
        run.trace.checks.append(f"Confidence {confidence:.2f} = ({terms}) / {sum(CONFIDENCE_WEIGHTS.values()):.2f}, "
                                "with the weights fixed in code.")
        run.trace.checks.append(
            f"The {len(levels)} reports span {spread} level{'s' if spread != 1 else ''} ({', '.join(levels)}): "
            + ("needs review, so the alert goes out as an advisory." if needs_review else "no review needed."))

        low, high = min(levels, key=level_index), max(levels, key=level_index)
        severity = out.severity
        if level_index(severity) < level_index(low) or level_index(severity) > level_index(high):
            severity = low if level_index(severity) < level_index(low) else high
            run.trace.checks.append(f"Moved the severity from {out.severity} to {severity}: it must stay between "
                                    f"{low} and {high}.")
        action = out.recommended_action
        if action == "close" and needs_review:
            action = "monitor"
            run.trace.checks.append("Changed close to monitor: an advisory asks rangers to confirm on site first.")
        elif action == "close" and level_index(severity) <= level_index("moderate"):
            action = "monitor"
            run.trace.checks.append(f"Changed close to monitor: a {severity} level does not close a trail.")

        avoid, safe = self._routes(out, remaining, run)
        response, response_checks = guards.clamp_response(out.response, severity, action, needs_review)
        run.trace.checks.extend(response_checks)
        run.trace.checks.append(
            f"Posture {response.posture} and priority {response.priority} are what a {severity} rating with "
            f"a {action} recommendation allows; code turns down anything louder.")

        payload = {
            "severity": severity,
            "confidence": confidence,
            "needs_review": needs_review,
            "recommended_action": action,
            "summary": out.summary,
            "analysis": out.analysis,
            "avoid": [route.model_dump() for route in avoid],
            "safe": [route.model_dump() for route in safe],
            "response": self._response_payload(response, action),
            "reports": {agent: report.severity for agent, report in reports.items()},
            "weights": CONFIDENCE_WEIGHTS,
            "safety_is_relative": comparative,
        }
        agreement = "All five reports agree." if spread == 0 else \
            f"The reports span {spread} level{'s' if spread != 1 else ''}" + \
            (", so this is an advisory." if needs_review else ".")
        await self._done(run, f"Final severity {severity}, confidence {confidence:.2f}. {agreement} "
                              f"Posture {response.posture}.", payload)
        return run

    def _routes(self, out: SynthesisReport, remaining: list[str], run: AgentRun):
        """The three and three the agent picked, checked against the catalog, or the code's own.

        A route the checks still reject after every attempt is replaced from the shortlist rather
        than dropped: the advisory always carries three of each, and the trace says which are the
        agent's and which are the code's.
        """
        broken = {problem.split(".")[1] for problem in remaining if problem.startswith(("avoid.", "safe."))}
        fallback_avoid, fallback_safe = guards.fallback_routes(
            self.scores, self.a.trail.name, self.a.bypass.name if self.a.bypass else None)
        avoid = self._merge_side(out.avoid, fallback_avoid, guards.avoid_pool(self.scores), "avoid",
                                 broken, remaining, run, lambda route: route.instead)
        safe = self._merge_side(out.safe, fallback_safe, guards.safe_pool(self.scores), "safe",
                                broken, remaining, run, lambda route: route.caution)
        return avoid, safe

    def _merge_side(self, chosen, fallback, pool, side: str, broken: set[str], remaining: list[str],
                    run: AgentRun, guidance):
        """One side of the advisory: the agent's sentences over the catalog's numbers."""
        merged, used = [], set()
        for index, route in enumerate(chosen):
            match = None if str(index) in broken else resolve(self.scores, route.trail)
            if match is not None and match.name not in used:
                merged.append(guards.merge_route(match, route.reason, guidance(route)))
                used.add(match.name)
        if len(merged) < 3:
            missing = [f for f in fallback if resolve(self.scores, f.trail) and
                       resolve(self.scores, f.trail).name not in used]
            spare = [s for s in pool if s.name not in used]
            for filler in missing:
                if len(merged) >= 3:
                    break
                match = resolve(self.scores, filler.trail)
                merged.append(guards.merge_route(match, filler.reason,
                                                 getattr(filler, "instead", None) or filler.caution))
                used.add(match.name)
            for score in spare:  # only if the fallback itself could not fill three
                if len(merged) >= 3:
                    break
                if score.name in used:
                    continue
                merged.append(guards.merge_route(
                    score, f"The map puts the {score.name} at {score.level}, peaking at "
                           f"{score.max_probability:.2f}.",
                    "See the catalog numbers above."))
                used.add(score.name)
            run.trace.checks.append(
                f"Filled the {side} list from the code's own shortlist: the agent's picks did not pass the "
                "catalog check after every attempt.")
        return merged[:3]

    @staticmethod
    def _response_payload(response, action: str) -> dict:
        return AdvisoryResponse(
            posture=response.posture,
            posture_rank=guards.posture_rank(response.posture),
            priority=response.priority,
            priority_rank=guards.priority_rank(response.priority),
            recommended_action=action,
            headline=response.headline,
            channels=list(response.channels),
            actions=list(response.actions),
            staffing=response.staffing,
            timeline=response.timeline,
            escalate_if=response.escalate_if,
        ).model_dump()

    async def writer(self) -> AgentRun:
        synth = self.runs["synthesizer"].payload
        terrain = self.runs["terrain"].payload["hazard_zone"]
        weather = self.runs["weather"].payload
        flagged, bypass, trail = self.a.flagged, self.a.bypass, self.a.trail.name
        title = ranger_line(terrain["type"], synth["severity"], terrain["place"], trail,
                            flagged.start_mile if flagged else None, flagged.end_mile if flagged else None,
                            synth["confidence"], synth["needs_review"])
        context = {"Final assessment": {
            "severity": synth["severity"],
            "confidence": synth["confidence"],
            "needs_review": synth["needs_review"],
            "recommended_action": synth["recommended_action"],
            "summary": synth["summary"],
            # The Synthesizer decided the posture. The Writer matches its tone to it and never
            # writes copy louder or quieter than the posture the code allowed.
            "ranger_posture": synth["response"]["posture"],
            "ranger_priority": synth["response"]["priority"],
            "ranger_headline": synth["response"]["headline"],
            "routes_to_avoid": [route["trail"] for route in synth["avoid"]],
            "safe_routes": [route["trail"] for route in synth["safe"]],
            "ranger_title": title,
            "hazard": {"type": terrain["type"], "place": terrain["place"], "drivers": terrain["drivers"],
                       "trail": trail, "miles": mile_text(flagged.start_mile, flagged.end_mile) if flagged else None},
            "rain_inches": {"past_72h": round(weather["rain_past_72h_mm"] / 25.4, 2),
                            "next_24h": round(weather["rain_next_24h_mm"] / 25.4, 2),
                            "source": weather["rain_source"]},
            "bypass": None if bypass is None else {
                "name": bypass.name,
                "leaves_at": f"mile {bypass.leaves_at_mile:.1f}",
                "rejoins_at": f"mile {bypass.rejoins_at_mile:.1f}",
                "added_distance": signed_miles(bypass.added_km),
                "added_climb": signed_feet(bypass.added_elevation_m),
            },
        }}

        def check(draft: AlertDraft) -> list[str]:
            return writer_problems(draft, trail, bypass.name if bypass else None, flagged is not None,
                                   synth["needs_review"])

        run, remaining = await self._call(
            "writer", signals=Signals(final_level=synth["severity"], needs_review=synth["needs_review"]),
            running="Drafting the ranger alert and the hiker card.", tools=[], context=context, check=check,
            soft_check=True)
        if run.error:
            return run
        draft: AlertDraft = run.output
        texts = {"ranger_body": draft.ranger_body, "hiker": draft.hiker, "what": draft.what, "why": draft.why,
                 "how_to_avoid": draft.how_to_avoid}
        if remaining:
            fallback = self._template_texts(title, synth)
            for field_name in fallback:
                if any(problem.startswith(field_name) for problem in remaining):
                    texts[field_name] = fallback[field_name]
                    run.trace.checks.append(f"Used the plain template for {field_name}: the model's text still "
                                            "failed a copy check after every try.")
        run.trace.checks.append("The ranger title is the design addendum's ranger line, filled in by code.")
        payload = {
            "recommended_action": synth["recommended_action"],
            "ranger": {"title": title, "body": texts["ranger_body"]},
            "hiker": texts["hiker"],
            "hazard": {"what": texts["what"], "why": texts["why"], "how_to_avoid": texts["how_to_avoid"]},
        }
        await self._done(run, "Ranger alert and hiker sentence ready.", payload)
        return run

    def _template_texts(self, title: str, synth: dict) -> dict[str, str]:
        """Plain fallback text built from facts, for fields the model could not get right."""
        facts = describe(self.a)
        trail, bypass = self.a.trail.name, self.a.bypass
        action = "Close the segment" if synth["recommended_action"] == "close" else "Monitor the segment"
        if bypass is not None:
            hiker = f"Steep, loose ground above the {trail} could slide onto the path, so take the {bypass.name} instead."
            action += f" and route hikers onto the {bypass.name}."
        else:
            hiker = f"Steep, loose ground above part of the {trail} could slide onto the path, so turn back before it."
            action += "."
        body = f"{title} {action}" if not synth["needs_review"] else f"{title.removesuffix(' Confirm on site before closing.')} {action} Confirm on site before closing."
        return {
            "ranger_body": body,
            "hiker": hiker,
            "what": facts["what"] or f"No mile of the {trail} reaches high.",
            "why": facts["why"] or "The map shows no high ground on the trail.",
            "how_to_avoid": facts["how_to_avoid"] or "No detour is needed.",
        }

    def _final(self) -> Final:
        synth = self.runs["synthesizer"].payload
        terrain = self.runs["terrain"].payload["hazard_zone"]
        weather: WeatherReport = self.runs["weather"].output
        writer = self.runs["writer"].payload
        drivers = list(terrain["drivers"])
        if weather.modifier == "worse":
            facts = self._tool(self.runs["weather"], "get_weather") or {}
            rain_driver = "recent_rain" if facts.get("past_72h_vs_threshold", 0) >= 1 else "forecast_rain"
            if rain_driver not in drivers:
                drivers.append(rain_driver)
        final = Final(
            hazard_type=terrain["type"],
            severity=synth["severity"],
            confidence=synth["confidence"],
            needs_review=synth["needs_review"],
            recommended_action=synth["recommended_action"],
            summary=synth["summary"],
            drivers=drivers,
            ranger_title=writer["ranger"]["title"],
            ranger_body=writer["ranger"]["body"],
            hiker=writer["hiker"],
            what=writer["hazard"]["what"],
            why=writer["hazard"]["why"],
            how_to_avoid=writer["hazard"]["how_to_avoid"],
        )
        final.advisory = self._advisory(final)
        return final

    def _advisory(self, final: Final) -> Advisory:
        """The run's whole conclusion in one object: what GET /runs/{id}/advisory returns."""
        synth = self.runs["synthesizer"].payload
        terrain = self.runs["terrain"].payload["hazard_zone"]
        prediction = self._tool(self.runs["terrain"], "get_model_prediction") or {}
        weather_facts = self._tool(self.runs["weather"], "get_weather")
        zone, flagged, bypass = self.a.zone, self.a.flagged, self.a.bypass

        hazard = None
        if zone is not None:
            hazard = AdvisoryHazard(
                type=final.hazard_type,
                severity=final.severity,
                place=terrain["place"],
                max_probability=terrain["max_probability"],
                area_km2=zone.area_km2,
                drivers=final.drivers,
                trail=self.a.trail.name,
                start_mile=flagged.start_mile if flagged else None,
                end_mile=flagged.end_mile if flagged else None,
                bypass_name=bypass.name if bypass else None,
                bypass_added_mi=round(bypass.added_km / 1.609344, 1) if bypass else None,
                bypass_added_ft=int(round(bypass.added_elevation_m * 3.28084 / 10) * 10) if bypass else None,
            )

        conditions = None
        if weather_facts is not None:
            extra = weather_facts["conditions"]
            conditions = AdvisoryConditions(
                source=weather_facts["source"],
                as_of=weather_facts["as_of"],
                rain_past_72h_mm=weather_facts["mm"]["past_72h"],
                rain_next_24h_mm=weather_facts["mm"]["next_24h"],
                rain_past_72h_in=weather_facts["inches"]["past_72h"],
                rain_next_24h_in=weather_facts["inches"]["next_24h"],
                temp_now_c=extra["temperature_c_now"],
                temp_min_next_72h_c=extra["temperature_c_next_72h"]["min"],
                temp_max_next_72h_c=extra["temperature_c_next_72h"]["max"],
                freeze_thaw_cycles_next_72h=extra["freeze_thaw_cycles_next_72h"],
                snowfall_next_72h_cm=extra["snowfall_cm_next_72h"],
                wind_max_next_24h_kmh=extra["wind_kmh_max_next_24h"],
                soil_moisture_now=extra["soil_moisture_top_7cm_now"],
                freezing_level_now_m=extra["freezing_level_m_now"],
            )

        map_summary = prediction.get("map") or self.a.map_summary
        return Advisory(
            run_id=self.ctx.run_id,
            mountain_slug=self.ctx.slug,
            mountain=self.ctx.mountain,
            generated_at=datetime.now(UTC),
            severity=final.severity,
            confidence=final.confidence,
            needs_review=final.needs_review,
            summary=final.summary,
            analysis=synth["analysis"],
            hazard=hazard,
            avoid=[AdvisoryRoute.model_validate(route) for route in synth["avoid"]],
            safe=[AdvisoryRoute.model_validate(route) for route in synth["safe"]],
            response=AdvisoryResponse.model_validate(synth["response"]),
            conditions=conditions,
            model=AdvisoryModel(
                method=self.a.method,
                is_stand_in=self.a.probability.is_stand_in,
                note=prediction.get("method_note", ""),
                map_max=map_summary.get("max"),
                map_mean=map_summary.get("mean"),
                share_at_high=round(sum(map_summary["share"][level] for level in ("high", "extreme")), 3)
                if map_summary.get("share") else None,
            ),
            alert=AdvisoryAlert(
                title=final.ranger_title,
                body=final.ranger_body,
                hiker=final.hiker,
                what=final.what,
                why=final.why,
                how_to_avoid=final.how_to_avoid,
            ),
            agents=self._verdicts(),
            checks=[check for agent in AGENT_ORDER if (run := self.runs.get(agent)) and run.trace
                    for check in run.trace.checks],
        )

    def _verdicts(self) -> dict[AgentName, AgentVerdict]:
        """Each agent's rating and who answered it, so the panel can show where they agreed."""
        verdicts: dict[AgentName, AgentVerdict] = {}
        for agent in AGENT_ORDER:
            run = self.runs.get(agent)
            if run is None:
                continue
            payload = run.payload
            severity = payload.get("severity")
            if agent == "terrain":
                severity = payload.get("hazard_zone", {}).get("severity")
            verdicts[agent] = AgentVerdict(
                label=AGENT_LABELS[agent],
                severity=severity,
                confidence=payload.get("confidence") or payload.get("hazard_zone", {}).get("confidence"),
                provider=run.trace.route.provider if run.trace else None,
                model=run.trace.route.label if run.trace else None,
                latency_ms=run.trace.latency_ms if run.trace else None,
            )
        return verdicts


# --- CLI ------------------------------------------------------------------------------------


async def _main(fixture_rain: bool, slug: str) -> int:
    from app import packs
    from app.assessment import assess
    from app.db import connect
    from app.weather import try_hourly_rain

    from .providers import make_providers

    pack = packs.get(slug)
    if pack is None:
        raise SystemExit(f"no pack facts for {slug!r} in data/seed/packs/index.json")
    if fixture_rain:
        os.environ["OPEN_METEO_FIXTURE"] = "backend/fixtures/open_meteo_storm.json"
    with connect() as conn:
        assessment = assess(conn, slug)
    # Without rain, the Weather Analyst fails and says why.
    rain, rain_error = try_hourly_rain(pack.peak_lat, pack.peak_lon)
    ctx = RunContext(run_id=f"cli-{uuid.uuid4().hex[:8]}", slug=slug, mountain=pack.name,
                     peak=(pack.peak_lat, pack.peak_lon), assessment=assessment, rain=rain, rain_error=rain_error)
    providers = make_providers()
    router = Router(providers)

    async def show(event: AgentEvent) -> None:
        route = f" [{event.trace.route.label}: {event.trace.route.reason}]" if event.status == "running" and event.trace else ""
        print(f"{event.agent:<11} {event.status:<7} {event.summary}{route}")

    started = time.perf_counter()
    result = await Pipeline(ctx, router, providers, show).run()
    print(f"\nstatus {result.status} in {time.perf_counter() - started:.1f} s")
    if result.final is None:
        print(f"failed at {result.failed_agent}: {result.error}")
        return 1
    advisory = result.final.advisory
    print(f"\n{'=' * 78}\nADVISORY\n{'=' * 78}")
    print(json.dumps(advisory.model_dump(mode="json"), indent=2))
    print(f"\n{advisory.response.posture.upper()} / {advisory.response.priority}: "
          f"{advisory.response.headline}")
    print("\nAvoid:")
    for route in advisory.avoid:
        print(f"  - {route.trail} ({route.level}, peak {route.max_probability:.2f}): {route.reason}")
    print("Safe:")
    for route in advisory.safe:
        print(f"  - {route.trail} ({route.level}, peak {route.max_probability:.2f}): {route.reason}")
    print("\nRangers:")
    for action in advisory.response.actions:
        print(f"  - {action}")
    print(f"  channels: {', '.join(advisory.response.channels)}")
    print(f"\nRanger: {result.final.ranger_title}\n{result.final.ranger_body}\n\nHiker: {result.final.hiker}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the agents once for one mountain and print the advisory.")
    parser.add_argument("--slug", default="mount-rainier", help="a pack slug from data/seed/packs/index.json")
    parser.add_argument("--fixture-rain", action="store_true",
                        help="read backend/fixtures/open_meteo_storm.json (a synthetic storm) instead of Open-Meteo")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.fixture_rain, args.slug)))


if __name__ == "__main__":
    main()
