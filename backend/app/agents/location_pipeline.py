"""Agent run for a mountain that has a summit, weather, and the cell classifier, and no trails.

Rainier's pipeline scores a mapped trail network. This one does not invent a replacement network.
Trail and Route Scout finish in code with an empty catalog. Terrain, Weather, and History still
call a model, and the Synthesizer decides from those reports plus the classifier state.
"""

from datetime import UTC, datetime

from app.agents.advisory import clamp_response
from app.agents.pipeline import (
    ANALYSTS,
    CONFIDENCE_WEIGHTS,
    AgentRun,
    Final,
    Pipeline,
    PipelineResult,
    weighted_confidence,
    writer_problems,
)
from app.agents.router import Signals
from app.agents.schemas import (
    Advisory,
    AdvisoryAlert,
    AdvisoryConditions,
    AdvisoryModel,
    AdvisoryResponse,
    AlertDraft,
    HistoryReport,
    LocationSynthesis,
    TerrainReport,
)
from app.ml.geo_susceptibility import PLACEHOLDER_INPUT, REAL_INPUT, predict_summit
from app.ml.risk_contract import production_decision_eligible
from app.risk import level_index, level_spread

LOCATION_RULES = """You are one agent in TerraSense. This mountain has no mapped trails and no baked terrain raster.
Use only the facts in this message. Never invent a trail name, a mile marker, a bypass, or a past landslide.
The production_72h_classification block is the decision source when decision_eligible is true: explain its
calibrated probability, state, and risk_level, never recompute or contradict them. The regional terrain
model_prediction block is visualization/context only; placeholder_terrain_sample means it scored labeled
stand-in terrain, not this summit's own ground. An UNCERTAIN classifier means insufficient evidence, not safety.
Risk levels are low, moderate, high, extreme.
Write plain sentences. No markdown. Return only the JSON object the schema asks for."""

TERRAIN_SYSTEM = LOCATION_RULES + """
You are the Terrain Analyst. There is no hazard polygon. Describe the summit from the model prediction.
- type: landslide.
- severity: the production classifier's risk_level when decision_eligible. Otherwise describe the regional
  terrain context as provisional and keep the run advisory.
- drivers: slope_angle, plus recent_rain or forecast_rain only when the weather block supports them.
- place: the mountain's name. Do not name a trail.
- confidence: at most 0.5 when input_source is placeholder_terrain_sample, and at most 0.45 when there is
  no model answer and the classifier state is UNCERTAIN."""

WEATHER_SYSTEM = LOCATION_RULES + """
You are the Weather Analyst. Say whether the rain at this summit makes the ground worse, stable, or better.
Use the rain totals in the tool results. Do not mention a trail."""

HISTORY_SYSTEM = LOCATION_RULES + """
You are the History Analyst. The catalog is the only record. An empty catalog is not evidence of safety.
precedent is none when the tool returns no events. severity stays moderate when the record is empty."""

SYNTH_SYSTEM = LOCATION_RULES + """
You are the Risk Synthesizer. You see every analyst report. Decide the severity, whether to monitor or
close, and the ranger response. Do not name a trail. coverage_note must say that no trails are mapped.
recommended_action is close only when the production classifier is decision_eligible and HIGH_RISK.
Otherwise monitor. When the classifier is UNCERTAIN or the regional terrain is a placeholder, the response
is an advisory to confirm on site."""

WRITER_SYSTEM = LOCATION_RULES + """
You are the Alert Writer. Write the ranger text and one hiker sentence.
Do not name a trail or a bypass. The hiker sentence is at most 25 words and contains no digits.
how_to_avoid says there is no mapped route to switch to.
When needs_review is true, ranger_body starts with "Advisory." and ends with "Confirm on site before closing." """


def _facts(ctx_runs: dict, agent: str) -> dict:
    run = ctx_runs.get(agent)
    if run and run.trace:
        for call in run.trace.tools:
            if call.name == "get_location_facts":
                return call.result or {}
    return {}


def _state(ctx_runs: dict, agent: str) -> str:
    facts = _facts(ctx_runs, agent)
    return (facts.get("cell_classification") or {}).get("state") or "UNCERTAIN"


def _geo(ctx_runs: dict, agent: str) -> dict:
    """The regional model's answer from the run's own tool result, so the panel shows what the agent saw."""
    facts = _facts(ctx_runs, agent)
    return facts.get("model_prediction") or {"available": False}


class LocationPipeline(Pipeline):
    """The same seven agent cards, with route lists left empty."""

    async def run(self) -> PipelineResult:
        await self.terrain()
        await self.weather()
        await self.trail()
        await self.history()
        await self.routes()
        failed = self._first_failure()
        if failed is None:
            await self.synthesizer()
            failed = self._first_failure()
        if failed is None:
            await self.writer()
            failed = self._first_failure()
        if failed is not None:
            return PipelineResult("error", self.runs, self.events, failed_agent=failed, error=self.runs[failed].error)
        return PipelineResult("done", self.runs, self.events, final=self._location_final())

    def _facts_tool(self) -> tuple[str, dict]:
        return ("get_location_facts", {"mountain": self.ctx.slug})

    async def terrain(self) -> AgentRun:
        lat, lon = self.ctx.peak
        # Cached, so the tool call inside the run pays nothing extra; the router just needs
        # the model's peak before the call the way the Rainier pipeline uses the zone peak.
        peak = predict_summit(self.ctx.slug, lat, lon).get("probability")
        run, _ = await self._call(
            "terrain",
            signals=Signals(zone_peak=peak),
            running="Scoring the regional terrain model at this summit.",
            tools=[self._facts_tool(), ("get_historical_events", {"lat": lat, "lon": lon, "radius_km": 30})],
            context={},
            system=TERRAIN_SYSTEM,
        )
        if run.error:
            return run
        out: TerrainReport = run.output
        state = _state(self.runs, "terrain")
        geo = _geo(self.runs, "terrain")
        location_facts = _facts(self.runs, "terrain")
        classifier = location_facts.get("cell_classification") or {}
        severity = out.severity
        if production_decision_eligible(classifier) and classifier.get("risk_level"):
            severity = classifier["risk_level"]
            if severity != out.severity:
                run.trace.checks.append(f"Moved the severity from {out.severity} to {severity}: the calibrated "
                                        "classifier is the decision source, and agent prose cannot override it.")
        elif geo.get("available") and geo.get("risk_level") and severity != geo["risk_level"]:
            severity = geo["risk_level"]
            run.trace.checks.append(f"Moved the display severity from {out.severity} to {severity}: the regional "
                                    "terrain model supplies context, not a production closure decision.")
        place = self.ctx.mountain if "trail" in out.place.lower() else out.place
        if place != out.place:
            run.trace.checks.append("Replaced the place with the mountain name: no trail is mapped here.")
        payload = {
            "hazard_zone": {
                "id": None,
                "type": out.type,
                "severity": severity,
                "max_probability": geo.get("probability"),
                "drivers": list(out.drivers),
                "confidence": out.confidence,
                "place": place,
                "notes": out.notes,
            },
            "cell_state": state,
            "classifier_decision_eligible": production_decision_eligible(classifier),
            "classifier_probability": classifier.get("calibrated_probability"),
            "classifier_threshold": classifier.get("high_risk_threshold"),
            "classifier_reason_codes": list(classifier.get("reason_codes") or []),
            "model_prediction": {
                "available": geo.get("available", False),
                "probability": geo.get("probability"),
                "risk_level": geo.get("risk_level"),
                "input_source": geo.get("input_source"),
            },
            "method": geo["method"] if geo.get("available") else "location cell classification",
            "severity": severity,
            "confidence": out.confidence,
        }
        if geo.get("available"):
            stand_in = " on stand-in terrain" if geo.get("input_source") == PLACEHOLDER_INPUT else ""
            run.trace.checks.append(
                f"The regional model puts this summit at {geo['probability']:.2f} ({geo['risk_level']}){stand_in}. "
                f"Production classifier state is {state}; terrain output remains context unless calibrated.")
            summary = (f"Model {geo['risk_level']} at {geo['probability']:.2f}{stand_in} for {place}. "
                       f"Classifier {state.replace('_', ' ').lower()}.")
        else:
            run.trace.checks.append(f"No model answer ({geo.get('reason', 'unavailable')}); "
                                    f"cell classifier state is {state}. No terrain raster was scored.")
            summary = f"Cell classification {state.replace('_', ' ').lower()} at {place}."
        await self._done(run, summary, payload)
        return run

    async def weather(self) -> AgentRun:
        lat, lon = self.ctx.peak
        run, _ = await self._call(
            "weather",
            signals=Signals(),
            running="Checking past and forecast rain at this summit.",
            tools=[self._facts_tool(), ("get_weather", {"lat": lat, "lon": lon})],
            context={},
            system=WEATHER_SYSTEM,
        )
        if run.error:
            return run
        out = run.output
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
        run.trace.checks.append("Rain totals come from the weather facts, not the model.")
        await self._done(
            run,
            f"{facts['mm']['past_72h']:.0f} mm in the past 72 hours and {facts['mm']['next_24h']:.0f} mm in the next 24.",
            payload,
        )
        return run

    async def trail(self) -> AgentRun:
        summary = "No trails are mapped here, so this run does not name a route."
        payload = {"trail_name": None, "severity": "moderate", "confidence": 0.2, "note": summary}
        run = AgentRun("trail", payload=payload)
        self.runs["trail"] = run
        await self._event("trail", "running", "Looking for mapped trails.")
        await self._event("trail", "done", summary, payload)
        return run

    async def history(self) -> AgentRun:
        lat, lon = self.ctx.peak
        run, _ = await self._call(
            "history",
            signals=Signals(),
            running="Reading the landslide record near this summit.",
            tools=[self._facts_tool(), ("get_historical_events", {"lat": lat, "lon": lon, "radius_km": 30})],
            context={},
            system=HISTORY_SYSTEM,
        )
        if run.error:
            return run
        out: HistoryReport = run.output
        facts = self._tool(run, "get_historical_events") or {"events": []}
        events = facts.get("events", [])
        if not events and out.precedent != "none":
            run.trace.checks.append("Set the precedent to none: the catalog returned no event.")
            out = out.model_copy(update={"precedent": "none"})
        payload = {
            "precedent": out.precedent,
            "severity": out.severity,
            "confidence": out.confidence,
            "events_within_radius": len(events),
            "note": out.note,
        }
        summary = "No catalog landslide near this summit. Absence of record, not absence of risk." if not events \
            else f"{len(events)} past slides within {facts.get('radius_km', 30):.0f} km."
        await self._done(run, summary, payload)
        return run

    async def routes(self) -> AgentRun:
        summary = "No trail catalog for this mountain."
        payload = {"severity": "moderate", "confidence": 0.2, "exposed": [], "clear": [], "trails_scored": 0, "note": summary}
        run = AgentRun("routes", payload=payload)
        self.runs["routes"] = run
        await self._event("routes", "running", "Checking the route catalog.")
        await self._event("routes", "done", summary, payload)
        return run

    async def synthesizer(self) -> AgentRun:
        reports = {agent: self.runs[agent].payload for agent in ANALYSTS}
        levels = tuple(report["severity"] for report in reports.values())
        confidence = weighted_confidence({
            agent: report.get("confidence") or report.get("hazard_zone", {}).get("confidence") or 0.2
            for agent, report in reports.items()
        })
        state = self.runs["terrain"].payload.get("cell_state", "UNCERTAIN")
        geo = self.runs["terrain"].payload.get("model_prediction") or {"available": False}
        cell = _facts(self.runs, "terrain").get("cell_classification") or {}
        classifier_eligible = production_decision_eligible(cell)
        placeholder = geo.get("input_source") == PLACEHOLDER_INPUT
        spread = level_spread(levels)
        # A run on stand-in terrain, or with no model answer and an uncovered classifier, goes
        # out as an advisory: the numbers are live but the ground is not confirmed on site.
        needs_review = spread >= 2 or placeholder or (not geo.get("available") and state == "UNCERTAIN")
        if self.ctx.production_prediction is not None and not classifier_eligible:
            needs_review = True
        # Closing is allowed only on the model's own ground (or a HIGH_RISK classifier), never
        # on a placeholder sample.
        may_close = (classifier_eligible and state == "HIGH_RISK") if self.ctx.production_prediction is not None else state == "HIGH_RISK" or (
            geo.get("available") and geo.get("input_source") == REAL_INPUT
            and geo.get("risk_level") in ("high", "extreme")
        )
        context = {f"{agent}": reports[agent] for agent in ANALYSTS}
        context["Computed by code"] = {
            "cell_state": state,
            "model_available": geo.get("available", False),
            "model_probability": geo.get("probability"),
            "model_risk_level": geo.get("risk_level"),
            "model_input_source": geo.get("input_source"),
            "classifier_decision_eligible": classifier_eligible,
            "classifier_probability": cell.get("calibrated_probability"),
            "classifier_threshold": cell.get("high_risk_threshold"),
            "classifier_reason_codes": list(cell.get("reason_codes") or []),
            "final_confidence": round(confidence, 2),
            "needs_review": needs_review,
            "weights": CONFIDENCE_WEIGHTS,
        }

        def check(report: LocationSynthesis) -> list[str]:
            problems = []
            if not may_close and report.recommended_action == "close":
                problems.append("recommended_action must be monitor: neither the model on this summit's own "
                                "terrain nor the cell classifier supports a closure.")
            if "trail" in report.coverage_note.lower() and "no trail" not in report.coverage_note.lower():
                problems.append("coverage_note must say that no trails are mapped.")
            return problems

        run, remaining = await self._call(
            "synthesizer",
            signals=Signals(),
            running="Weighing the summit, the classifier, and the weather.",
            tools=[],
            context=context,
            check=check,
            soft_check=True,
            system=SYNTH_SYSTEM,
            output_model=LocationSynthesis,
        )
        if run.error:
            return run
        out: LocationSynthesis = run.output
        severity = out.severity
        low, high = min(levels, key=level_index), max(levels, key=level_index)
        if level_index(severity) < level_index(low) or level_index(severity) > level_index(high):
            severity = low if level_index(severity) < level_index(low) else high
            run.trace.checks.append(f"Moved the severity from {out.severity} to {severity}.")
        if classifier_eligible and cell.get("risk_level") and severity != cell["risk_level"]:
            run.trace.checks.append(
                f"Moved the severity from {severity} to {cell['risk_level']}: the calibrated classifier is "
                "the decision source."
            )
            severity = cell["risk_level"]
        action = out.recommended_action
        if not may_close and action == "close":
            action = "monitor"
            run.trace.checks.append("Changed close to monitor: only an eligible calibrated HIGH_RISK classifier "
                                    "decision can authorize a closure.")
        if "close" in remaining and action == "close":
            action = "monitor"
        if placeholder:
            run.trace.checks.append("The model scored a stand-in terrain sample, so the run goes out as an "
                                    "advisory to confirm on site.")
        response, response_checks = clamp_response(out.response, severity, action, needs_review)
        run.trace.checks.extend(response_checks)
        run.trace.checks.append("No routes were attached: this mountain has no mapped trails.")
        payload = {
            "severity": severity,
            "confidence": round(confidence, 2),
            "needs_review": needs_review,
            "recommended_action": action,
            "summary": out.summary,
            "analysis": out.analysis,
            "avoid": [],
            "safe": [],
            "response": self._response_payload(response, action),
            "coverage_note": out.coverage_note,
        }
        await self._done(run, f"Final severity {severity}. No trails to close or recommend.", payload)
        return run

    async def writer(self) -> AgentRun:
        synth = self.runs["synthesizer"].payload
        title = (
            f"Landslide risk {synth['severity'].upper()}. {self.ctx.mountain}, no mapped trails. "
            f"Confidence {synth['confidence']:.2f}."
        )
        if synth["needs_review"]:
            title = f"Advisory. {title} Confirm on site before closing."
        context = {"Final assessment": {
            "ranger_title": title,
            "severity": synth["severity"],
            "needs_review": synth["needs_review"],
            "recommended_action": synth["recommended_action"],
            "summary": synth["summary"],
            "hazard": {"type": "landslide", "trail": None, "miles": None},
            "bypass": None,
        }}
        run, remaining = await self._call(
            "writer",
            signals=Signals(),
            running="Writing the alert from the summit call.",
            tools=[],
            context=context,
            check=lambda draft: writer_problems(draft, "", None, False, synth["needs_review"]),
            system=WRITER_SYSTEM,
            output_model=AlertDraft,
        )
        if run.error:
            return run
        draft: AlertDraft = run.output
        texts = {
            "ranger_body": draft.ranger_body,
            "hiker": draft.hiker,
            "what": draft.what,
            "why": draft.why,
            "how_to_avoid": draft.how_to_avoid,
        }
        if remaining:
            fallback = self._template(title, synth["needs_review"])
            for field_name, text in fallback.items():
                if any(problem.startswith(field_name) for problem in remaining):
                    texts[field_name] = text
                    run.trace.checks.append(f"Used the plain template for {field_name}.")
        payload = {
            "recommended_action": synth["recommended_action"],
            "ranger": {"title": title, "body": texts["ranger_body"]},
            "hiker": texts["hiker"],
            "hazard": {"what": texts["what"], "why": texts["why"], "how_to_avoid": texts["how_to_avoid"]},
        }
        await self._done(run, "Ranger alert ready. No trail was named.", payload)
        return run

    def _template(self, title: str, needs_review: bool) -> dict[str, str]:
        body = f"{title} No trails are mapped, so monitor the weather at the summit and look again after rain."
        if needs_review and not body.startswith("Advisory."):
            body = f"Advisory. {body}"
        if needs_review and not body.endswith("Confirm on site before closing."):
            body = f"{body.rstrip('.')} Confirm on site before closing."
        return {
            "ranger_body": body,
            "hiker": "Rain on steep ground can send debris downhill, and no trail is mapped here to reroute onto.",
            "what": f"Landslide risk at {self.ctx.mountain}, with no mapped trails.",
            "why": "The call uses the summit location, the cell classifier, and the rain.",
            "how_to_avoid": "No mapped route to switch to. Stay off steep ground below the summit in heavy rain.",
        }

    def _location_final(self):
        synth = self.runs["synthesizer"].payload
        terrain = self.runs["terrain"].payload["hazard_zone"]
        writer = self.runs["writer"].payload
        final = Final(
            hazard_type=terrain["type"],
            severity=synth["severity"],
            confidence=synth["confidence"],
            needs_review=synth["needs_review"],
            recommended_action=synth["recommended_action"],
            summary=synth["summary"],
            drivers=list(terrain["drivers"]),
            ranger_title=writer["ranger"]["title"],
            ranger_body=writer["ranger"]["body"],
            hiker=writer["hiker"],
            what=writer["hazard"]["what"],
            why=writer["hazard"]["why"],
            how_to_avoid=writer["hazard"]["how_to_avoid"],
        )
        final.advisory = self._location_advisory(final)
        return final

    def _location_advisory(self, final) -> Advisory:
        synth = self.runs["synthesizer"].payload
        weather_facts = self._tool(self.runs["weather"], "get_weather")
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
        state = self.runs["terrain"].payload.get("cell_state", "UNCERTAIN")
        loc = self._tool(self.runs["terrain"], "get_location_facts") or {}
        geo = loc.get("model_prediction") or {"available": False}
        cell = loc.get("cell_classification") or {}
        probability = geo.get("probability")
        if probability is None and cell.get("calibrated_probability") is not None:
            probability = cell["calibrated_probability"]
        if geo.get("available"):
            method = geo["method"]
            is_stand_in = geo.get("input_source") == PLACEHOLDER_INPUT
            note = geo.get("note", "")
        else:
            method = "location cell classification"
            is_stand_in = state == "UNCERTAIN"
            note = ("The cell classifier does not cover this summit." if state == "UNCERTAIN"
                    else f"Cell classifier state {state}.")
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
            hazard=None,
            avoid=[],
            safe=[],
            response=AdvisoryResponse.model_validate(synth["response"]),
            conditions=conditions,
            model=AdvisoryModel(
                method=method,
                is_stand_in=is_stand_in,
                note=note,
                map_max=probability,
                map_mean=None,
                share_at_high=None,
                classifier_state=cell.get("state"),
                classifier_probability=cell.get("calibrated_probability"),
                classifier_threshold=cell.get("high_risk_threshold"),
                classifier_decision_eligible=production_decision_eligible(cell),
                classifier_reason_codes=list(cell.get("reason_codes") or []),
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
            checks=["No trails are mapped, so the advisory names no route."],
        )
