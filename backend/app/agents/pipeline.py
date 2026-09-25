"""The five-agent pipeline (step 21).

Terrain and Weather run together, then Trail, the Risk Synthesizer, and the Alert Writer. For
each agent the router picks a provider, the agent's tools gather facts, and one model call returns
JSON that must pass the agent's schema and checks. The code then merges the facts back in. An
AgentEvent goes out when each agent starts and when it finishes or fails, with its full trace:
the route, the tool calls, every attempt, the model's reasoning, and what the code changed.

A call that fails is retried once on the same provider when the failure is temporary, and an
answer that fails a check is sent back once with the problems listed. After that the router's
fallback provider gets the same two chances. An agent fails only when both providers do.

Code, not a model, decides three things:
- confidence: the weighted average of the three analysts' confidence (CONFIDENCE_WEIGHTS);
- needs_review: set when two analysts' severities sit two or more levels apart, which turns the
  ranger alert into an advisory;
- the Synthesizer's guard rails: its severity stays within the analysts' range, and an advisory
  or a low or moderate level recommends "monitor", never "close".

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
from app.risk import RiskLevel, level_index, level_spread
from app.weather import summarize

from .prompts import REPAIR, SYSTEM_PROMPTS
from .providers import LLMRequest, LLMResult, Provider, ProviderError, llm_schema
from .router import NoProviderError, Router, Signals
from .schemas import (
    AGENT_LABELS,
    AGENT_ORDER,
    AGENT_OUTPUTS,
    AgentEvent,
    AgentName,
    AgentOutput,
    AgentTrace,
    AlertDraft,
    Attempt,
    ProviderName,
    SynthesisReport,
    TerrainReport,
    TrailReport,
    WeatherReport,
)
from .tools import RunContext, ToolError, call_tool, threshold_mm

# How much each analyst's confidence counts toward the final one. Terrain is the most direct
# evidence of where ground can fail; the weather is one reading for the whole box; the trail
# report restates the other two against the miles.
CONFIDENCE_WEIGHTS: dict[AgentName, float] = {"terrain": 0.40, "weather": 0.35, "trail": 0.25}
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
        await asyncio.gather(self.terrain(), self.weather())
        failed = self._first_failure()
        if failed is None:
            await self.trail()
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
                    soft_check: bool = False) -> tuple[AgentRun, list[str]]:
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
        try:
            trace.tools = [await asyncio.to_thread(call_tool, self.ctx, name, **args) for name, args in tools]
            request = LLMRequest(
                system=SYSTEM_PROMPTS[agent],
                user=self._message(agent, trace, context),
                schema=llm_schema(AGENT_OUTPUTS[agent]),
                schema_name=f"{agent}_report",
            )
            output, result, remaining = await self._ask(agent, decision.provider, decision.fallback, request,
                                                        trace, check, soft_check)
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
                   trace: AgentTrace, check, soft_check: bool) -> tuple[AgentOutput, LLMResult, list[str]]:
        """Two tries per provider, the router's pick first. See the module docstring."""
        model = AGENT_OUTPUTS[agent]
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

    async def terrain(self) -> AgentRun:
        zone = self.a.zone
        tools = [("get_raster_summary", {"mountain": self.ctx.slug})]
        if zone is not None:
            tools.append(("get_historical_events", {"lat": zone.centroid[1], "lon": zone.centroid[0], "radius_km": 5.0}))
        run, _ = await self._call("terrain", signals=Signals(zone_peak=zone.max_probability if zone else None),
                                  running="Reading the hazard zone on the 72-hour map.", tools=tools, context={})
        if run.error:
            return run
        out: TerrainReport = run.output
        drivers, dropped = list(out.drivers), []
        history = next((c.result for c in run.trace.tools if c.name == "get_historical_events"), {"events": []})
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
                                  running="Checking past and forecast rain at Paradise.",
                                  tools=[("get_weather", {"lat": lat, "lon": lon})], context={})
        if run.error:
            return run
        out: WeatherReport = run.output
        facts = run.trace.tools[0].result
        payload = {
            "modifier": out.modifier,
            "severity": out.severity,
            "confidence": out.confidence,
            "rain_past_72h_mm": facts["mm"]["past_72h"],
            "rain_next_24h_mm": facts["mm"]["next_24h"],
            "rain_source": facts["source"],
            "note": out.note,
        }
        run.trace.checks.append("Rain totals in the payload come from the Open-Meteo facts, not the model.")
        trend = {"worse": "The zone is getting worse.", "stable": "The zone holds steady.",
                 "better": "The zone is easing."}[out.modifier]
        await self._done(run, f"{facts['mm']['past_72h']:.0f} mm in the past 72 hours and "
                              f"{facts['mm']['next_24h']:.0f} mm in the next 24. {trend}", payload)
        return run

    async def trail(self) -> AgentRun:
        flagged, bypass = self.a.flagged, self.a.bypass
        signals = Signals(bypass_exists=(bypass is not None) if flagged else None,
                          bypass_level=bypass.level if bypass else None)
        context = {"Terrain Analyst's report": self.runs["terrain"].payload,
                   "Weather Analyst's report": self.runs["weather"].payload}
        run, _ = await self._call("trail", signals=signals, running="Checking the flagged miles and the bypass.",
                                  tools=[("get_trail_segments", {"mountain": self.ctx.slug})], context=context)
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
        run.trace.checks.append("The miles and the bypass come from code (steps 18 and 19); the model only explains them.")
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

    async def synthesizer(self) -> AgentRun:
        reports = {a: self.runs[a].output for a in ("terrain", "weather", "trail")}
        levels = tuple(r.severity for r in reports.values())
        confidence = weighted_confidence({a: r.confidence for a, r in reports.items()})
        spread = level_spread(levels)
        needs_review = spread >= REVIEW_SPREAD
        context = {
            "Terrain Analyst's report": self.runs["terrain"].payload,
            "Weather Analyst's report": self.runs["weather"].payload,
            "Trail Analyst's report": self.runs["trail"].payload,
            "Computed by code": {"final_confidence": confidence, "severity_spread_levels": spread,
                                 "needs_review": needs_review, "weights": CONFIDENCE_WEIGHTS},
        }
        run, _ = await self._call("synthesizer", signals=Signals(report_levels=levels),
                                  running="Combining the terrain, weather, and trail reports.", tools=[],
                                  context=context)
        if run.error:
            return run
        out: SynthesisReport = run.output
        terms = " + ".join(f"{reports[a].confidence:.2f} x {CONFIDENCE_WEIGHTS[a]:.2f}" for a in reports)
        run.trace.checks.append(f"Confidence {confidence:.2f} = ({terms}) / {sum(CONFIDENCE_WEIGHTS.values()):.2f}, "
                                "with the weights fixed in code.")
        run.trace.checks.append(
            f"The reports span {spread} level{'s' if spread != 1 else ''} ({', '.join(levels)}): "
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
        payload = {
            "severity": severity,
            "confidence": confidence,
            "needs_review": needs_review,
            "recommended_action": action,
            "summary": out.summary,
            "reports": {a: r.severity for a, r in reports.items()},
            "weights": CONFIDENCE_WEIGHTS,
        }
        agreement = "The three reports agree." if spread == 0 else \
            f"The reports span {spread} level{'s' if spread != 1 else ''}" + (", so this is an advisory." if needs_review else ".")
        await self._done(run, f"Final severity {severity}, confidence {confidence:.2f}. {agreement}", payload)
        return run

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
            facts = self.runs["weather"].trace.tools[0].result
            rain_driver = "recent_rain" if facts["past_72h_vs_threshold"] >= 1 else "forecast_rain"
            if rain_driver not in drivers:
                drivers.append(rain_driver)
        return Final(
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


# --- CLI ------------------------------------------------------------------------------------


async def _main(fixture_rain: bool) -> int:
    from app.assessment import LIVE_SLUG, assess
    from app.db import connect
    from app.weather import try_hourly_rain

    from .providers import make_providers

    if fixture_rain:
        os.environ["OPEN_METEO_FIXTURE"] = "backend/fixtures/open_meteo_storm.json"
    with connect() as conn:
        assessment = assess(conn, LIVE_SLUG)
    rain, rain_error = try_hourly_rain()  # without rain, the Weather Analyst fails and says why
    ctx = RunContext(run_id=f"cli-{uuid.uuid4().hex[:8]}", slug=LIVE_SLUG, mountain="Mount Rainier",
                     peak=(46.8523, -121.7603), assessment=assessment, rain=rain, rain_error=rain_error)
    providers = make_providers()
    router = Router(providers)

    async def show(event: AgentEvent) -> None:
        route = f" [{event.trace.route.label}: {event.trace.route.reason}]" if event.status == "running" and event.trace else ""
        print(f"{event.agent:<11} {event.status:<7} {event.summary}{route}")

    started = time.perf_counter()
    result = await Pipeline(ctx, router, providers, show).run()
    print()
    for agent in AGENT_ORDER:
        run = result.runs.get(agent)
        if run and run.payload:
            print(json.dumps({"agent": agent, "payload": run.payload}, indent=2))
    print(f"\nstatus {result.status} in {time.perf_counter() - started:.1f} s")
    if result.final is None:
        print(f"failed at {result.failed_agent}: {result.error}")
        return 1
    final = result.final
    print(f"final severity {final.severity}, confidence {final.confidence}, needs_review {final.needs_review}, "
          f"action {final.recommended_action}")
    print(f"\nRanger: {final.ranger_title}\n{final.ranger_body}\n\nHiker: {final.hiker}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the five agents once for Mount Rainier.")
    parser.add_argument("--fixture-rain", action="store_true",
                        help="read backend/fixtures/open_meteo_storm.json (a synthetic storm) instead of Open-Meteo")
    raise SystemExit(asyncio.run(_main(parser.parse_args().fixture_rain)))


if __name__ == "__main__":
    main()
