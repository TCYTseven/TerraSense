"""A stand-in for the Gemini and xAI APIs, for tests and offline development. Not for demos.

It answers all seven agents, including the five that fan out together, so an offline run exercises
the same parallel path a real one does.

It answers generateContent, /v1/responses, and /v1/chat/completions in each provider's wire
format, with an answer built from the facts in the prompt and a short reasoning summary. Every
answer names its model "fake-..." so nothing mistakes it for a real model.

    uvicorn tests.fake_llm:app --port 8090        (from backend/)
    GEMINI_BASE_URL=http://localhost:8090 XAI_BASE_URL=http://localhost:8090
    GEMINI_API_KEY=fake XAI_API_KEY=fake

Knobs, read on every request:
    FAKE_LLM_DELAY_S       seconds before each answer (default 1.5), so a UI shows work happening
    FAKE_LLM_FAIL          comma list of providers or provider:agent pairs that answer HTTP 503,
                           such as "gemini" or "gemini:terrain"
    FAKE_LLM_BAD_WRITER    "1": the Alert Writer's first answer breaks the copy rules, so the
                           pipeline has to send it back
    FAKE_LLM_BAD_ROUTES    "1": the Risk Synthesizer names trails that are not on the mountain, so
                           the catalog checks have to reject them
"""

import asyncio
import json
import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Fake LLM APIs (tests only)")

JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def _blocks(text: str) -> list:
    out = []
    for raw in JSON_BLOCK.findall(text):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _find(blocks: list, key: str, without: str | None = None):
    return next((b for b in blocks if isinstance(b, dict) and key in b
                 and (without is None or without not in b)), None)


def _arrays(blocks: list) -> list:
    """The bare JSON arrays in the prompt, such as the Synthesizer's route shortlists."""
    return [b for b in blocks if isinstance(b, list)]


def _raster(blocks: list) -> dict:
    """get_raster_summary's block, not get_model_prediction's: both carry a hazard_zone."""
    return _find(blocks, "hazard_zone", without="role") or {}


def _agent(properties: dict) -> str:
    if "place" in properties:
        return "terrain"
    if "modifier" in properties:
        return "weather"
    if "precedent" in properties:
        return "history"
    if "exposed" in properties:
        return "routes"
    if "recommended_action" in properties:
        return "synthesizer"
    if "hiker" in properties:
        return "writer"
    return "trail"


def terrain(blocks: list) -> tuple[dict, str]:
    summary = _raster(blocks)
    zone = summary.get("hazard_zone")
    stand_in = "stand-in" in (summary.get("method") or "")
    if not zone:
        return {"type": "landslide", "severity": "moderate", "drivers": ["slope_angle"], "confidence": 0.5,
                "place": "Along the hero trail", "notes": "No trail segment reaches high on the map.",
                "reasoning": ["The map has no hazard zone on the trail.", "The steepest ground stays moderate."]}, \
            "No zone to describe, so I kept the level moderate."
    terrain_facts = zone.get("terrain") or {}
    junctions = zone.get("nearby_junctions") or []
    anchor = junctions[0]["trails"][0] if junctions else zone["trail"]
    near = terrain_facts.get("share_near_channel", 0)
    answer = {
        "type": zone.get("type_hint", "landslide"),
        "severity": zone["level"],
        "drivers": (zone.get("drivers_hint") or ["slope_angle"])[:4],
        "confidence": 0.72 if stand_in else 0.82,
        "place": f"Near the {anchor} junction",
        "notes": f"The zone covers {zone['area_km2']} km2 of {terrain_facts.get('facing', 'open')}-facing ground where "
                 f"the {zone['trail']} crosses it.",
        "reasoning": [
            f"The zone peaks at {zone['max_probability']}, inside the {zone['level']} bin.",
            f"{round(near * 100)}% of the zone sits within 100 m of a channel.",
            "The map is a stand-in for the rain model, so confidence stays moderate." if stand_in
            else "The map includes the rain signal.",
        ],
    }
    return answer, f"Peak {zone['max_probability']} is {zone['level']}; checking channel share and cover."


def weather(blocks: list) -> tuple[dict, str]:
    facts = _find(blocks, "mm") or {}
    mm = facts.get("mm", {})
    past = facts.get("past_72h_vs_threshold", 0)
    ahead = mm.get("next_24h", 0)
    modifier = "worse" if past >= 1 and ahead >= 5 else "better" if past < 0.5 and ahead < 2 else "stable"
    severity = "extreme" if past >= 3 else "high" if past >= 1.5 else "moderate" if past >= 0.5 else "low"
    note = (f"{mm.get('past_72h', 0)} mm fell in the past 72 hours, {past}x the threshold, and {ahead} mm more is "
            "due in the next 24.")
    if facts.get("warning"):
        note += " This is a synthetic test storm."
    return {"modifier": modifier, "severity": severity, "confidence": 0.78, "note": note,
            "reasoning": [f"Past 72 hours: {past}x the Guzzetti threshold.",
                          f"Next 24 hours: {ahead} mm more on wet ground."]}, \
        f"Rain ratio {past}; forecast {ahead} mm."


def trail(blocks: list) -> tuple[dict, str]:
    facts = _find(blocks, "risk_by_mile") or {}
    flagged, bypass = facts.get("flagged"), facts.get("bypass") or {}
    if not flagged:
        return {"severity": "moderate", "confidence": 0.7, "note": f"No mile of the {facts.get('trail')} reaches high.",
                "reasoning": ["No flagged miles.", "No detour needed."]}, "Nothing flagged."
    miles = f"mile {flagged['start_mile']:.1f} to {flagged['end_mile']:.1f}"
    if bypass.get("exists"):
        note = (f"The {facts['trail']} crosses the zone from {miles}. The {bypass['name']} leaves at mile "
                f"{bypass['leaves_at_mile']:.1f} and rejoins at mile {bypass['rejoins_at_mile']:.1f}, "
                f"{bypass['added_mi']:+.1f} mi.")
        if bypass["worst_ground"]["level"] in ("high", "extreme"):
            note += f" It crosses {bypass['worst_ground']['level']} ground itself, so hikers should keep moving."
    else:
        note = f"The {facts['trail']} crosses the zone from {miles}, and no trail runs around it: turn back."
    return {"severity": flagged["level"], "confidence": 0.8, "note": note,
            "reasoning": [f"Segments from {miles} sit at {flagged['level']}.",
                          f"The bypass is the {bypass['name']}." if bypass.get("exists") else "There is no bypass."]}, \
        "Matching the flagged miles to the bypass."


def history(blocks: list) -> tuple[dict, str]:
    facts = _find(blocks, "events") or {}
    events = facts.get("events", [])
    zone = (_find(blocks, "hazard_zone") or {}).get("hazard_zone") or {}
    if not events:
        return {"precedent": "none", "severity": zone.get("level", "moderate"), "confidence": 0.35,
                "note": "The catalog holds no recorded slide within the search radius. That is an absence of "
                        "record, not an absence of risk.",
                "reasoning": ["No catalog event inside the radius.",
                              "An empty record cannot lower the level, so it stays at the map's."]}, \
            "Empty catalog: reading it as no evidence, not as evidence of safety."
    nearest = events[0]
    precedent = "strong" if len(events) >= 3 else "moderate" if len(events) == 2 else "weak"
    return {"precedent": precedent, "severity": zone.get("level", "moderate"), "confidence": 0.6,
            "note": f"{len(events)} past slides sit within the radius, the nearest {nearest.get('km_away')} km "
                    f"away ({nearest.get('trigger') or 'trigger unrecorded'}).",
            "reasoning": [f"{len(events)} catalog events near the zone.",
                          f"The nearest is {nearest.get('km_away')} km away."]}, \
        f"{len(events)} analogs; precedent {precedent}."


def routes(blocks: list) -> tuple[dict, str]:
    catalog = _find(blocks, "most_exposed") or {}
    exposed = catalog.get("most_exposed", [])[:3]
    clear = catalog.get("clearest", [])[:3]
    network = catalog.get("network", {})
    relative = network.get("clear_enough_to_recommend", 0) < 3
    worst = max((t["max_probability"] for t in exposed), default=0.5)
    severity = "extreme" if worst > 0.7 else "high" if worst >= 0.45 else "moderate" if worst >= 0.2 else "low"
    tail = (" None of them clears the safe ceiling, so they are the least exposed ground rather than safe ground."
            if relative else "")
    return {
        "exposed": [{"trail": t["trail"],
                     "note": f"{t['share_at_high_or_above']:.0%} of it sits at high or above, peaking at "
                             f"{t['max_probability']}."} for t in exposed],
        "clear": [{"trail": t["trail"],
                   "note": f"It peaks at {t['max_probability']}, in the {t['level']} band."} for t in clear],
        "severity": severity,
        "confidence": 0.7,
        "note": f"{network.get('at_high_or_above', 0)} of {network.get('trails', 0)} trails reach high or "
                f"above today.{tail}",
        "reasoning": [f"The worst trail peaks at {worst}.",
                      f"{network.get('clear_enough_to_recommend', 0)} trails clear the safe ceiling."],
    }, f"Scored {network.get('trails', 0)} trails; network severity {severity}."


LEVELS = ["low", "moderate", "high", "extreme"]


def synthesizer(blocks: list) -> tuple[dict, str]:
    terrain_report = (_find(blocks, "hazard_zone") or {}).get("hazard_zone", {})
    weather_report = _find(blocks, "modifier") or {}
    trail_report = _find(blocks, "trail_name") or {}
    history_report = _find(blocks, "precedent") or {}
    routes_report = _find(blocks, "trails_scored") or {}
    computed = _find(blocks, "final_confidence") or {}
    bypass = _find(blocks, "leaves_at_mile") or {}

    levels = [r.get("severity", "moderate") for r in
              (terrain_report, weather_report, trail_report, history_report, routes_report) if r]
    severity = max(levels, key=LEVELS.index) if levels else "moderate"
    review = bool(computed.get("needs_review"))
    action = "close" if severity in ("high", "extreme") and not review else "monitor"
    miles = f"mile {trail_report.get('start_mile', 0):.1f} to {trail_report.get('end_mile', 0):.1f}"

    # The shortlists the code put in the prompt: the only routes that pass its checks.
    avoid_pool = next((a for a in _arrays(blocks) if a and "max_probability" in a[0]), [])[:3]
    # The Route Scout's payload also carries safety_is_relative, so match on the shortlist's
    # own key instead.
    safe_block = _find(blocks, "trails") or {}
    safe_pool = (safe_block.get("trails") or [])[:3]
    relative = bool(safe_block.get("safety_is_relative"))
    instead = f"the {bypass['name']}" if bypass.get("name") else "one of the safe routes below"

    posture = {"low": "all_clear", "moderate": "watch", "high": "advisory", "extreme": "warning"}[severity]
    if action == "close" and severity == "extreme":
        posture = "warning"
    priority = {"all_clear": "routine", "watch": "routine", "advisory": "elevated",
                "warning": "urgent"}[posture]
    channels = (["newsletter", "website_banner"] if posture in ("all_clear", "watch")
                else ["trailhead_signage", "website_banner", "ranger_radio"])
    if os.environ.get("FAKE_LLM_BAD_ROUTES") == "1":
        # Trails that are nowhere in the catalog: the checks must reject every one of them.
        avoid_pool = [{"trail": f"Mordor Ridge {n}", "max_probability": 0.9, "share_at_high_or_above": 0.9,
                       "level": "extreme"} for n in range(3)]
        safe_pool = [{"trail": f"Rivendell Path {n}", "max_probability": 0.1, "level": "low"} for n in range(3)]

    answer = {
        "severity": severity,
        "recommended_action": action,
        "summary": f"Debris flow risk on the {trail_report.get('trail_name')}, {miles}: {action} the segment.",
        "avoid": [{"trail": t["trail"],
                   "reason": f"{t['share_at_high_or_above']:.0%} of it is at high or above, peaking at "
                             f"{t['max_probability']}.",
                   "instead": f"Send hikers to {instead}."} for t in avoid_pool],
        "safe": [{"trail": t["trail"],
                  "reason": f"It peaks at {t['max_probability']}, in the {t['level']} band.",
                  "caution": ("It is the least exposed ground today, not safe ground." if relative
                              else "Expect mud underfoot after the rain.")} for t in safe_pool],
        "response": {
            "posture": posture,
            "priority": priority,
            "headline": f"{severity.title()} landslide risk on the {trail_report.get('trail_name')}, {miles}.",
            "channels": channels,
            "actions": [f"{'Close' if action == 'close' else 'Watch'} the "
                        f"{trail_report.get('trail_name')} from {miles}.",
                        "Brief the desk so staff can redirect hikers.",
                        "Re-run the analysis after the next rain."],
            "staffing": "Put a ranger at the trailhead through the afternoon.",
            "timeline": "Act today and look again tomorrow morning.",
            "escalate_if": "Fresh debris or cracks appear on these miles.",
        },
        "analysis": f"The analysts rated this {', '.join(levels)}. The map puts the worst ground on "
                    f"{miles} of the {trail_report.get('trail_name')}, and the record "
                    f"{history_report.get('precedent', 'none')}ly supports it. The response is scaled to "
                    f"{posture} because the action is to {action}.",
        "reasoning": [f"Reports: {', '.join(levels)}.",
                      f"The top level is {severity}, so the action is {action}."],
    }
    return answer, f"Levels {levels}; taking the highest within range and scaling the response to {posture}."


def writer(blocks: list, repair: bool) -> tuple[dict, str]:
    final = (_find(blocks, "ranger_title") or {})
    hazard, bypass = final.get("hazard", {}), final.get("bypass")
    trail_name, miles = hazard.get("trail", "the trail"), hazard.get("miles") or "the flagged miles"
    review = final.get("needs_review")
    body = f"{final.get('ranger_title', '')} {'Close' if final.get('recommended_action') == 'close' else 'Monitor'} " \
           f"the {trail_name} from {miles}."
    if bypass:
        body += f" Route hikers onto the {bypass['name']}."
    if review:
        body = f"Advisory. {body.removeprefix('Advisory. ')}"
        body = body.replace(" Confirm on site before closing.", "") + " Confirm on site before closing."
    detour = f"take the {bypass['name']} instead" if bypass else "turn back before the slide area"
    hiker = f"Days of rain have loosened the slopes above the {trail_name}, so {detour}."
    if os.environ.get("FAKE_LLM_BAD_WRITER") == "1" and not repair:
        hiker = ("With a 0.96 probability of failure the model says the slopes above the trail between mile 4.6 "
                 "and 4.9 are very likely to slide in the next 72 hours so please be careful out there")
    rain = final.get("rain_inches", {})
    answer = {
        "ranger_body": body,
        "hiker": hiker,
        "what": f"A {hazard.get('type', 'landslide').replace('_', ' ')} zone on the {trail_name}, {miles}.",
        "why": f"Steep ground near a drainage took {rain.get('past_72h', 0):.2f} in of rain in 72 hours.",
        "how_to_avoid": (f"Leave at {bypass['leaves_at']} and take the {bypass['name']} to {bypass['rejoins_at']}."
                         if bypass else f"Turn back before {miles.split(' to ')[0]}."),
        "reasoning": ["The final level and action come from the Synthesizer.",
                      "The hiker sentence names the bypass without numbers."],
    }
    return answer, "Keeping the hiker line under 25 words and naming the bypass."


def _answer(properties: dict, user: str) -> tuple[str, dict, str]:
    agent = _agent(properties)
    blocks = _blocks(user)
    if agent == "writer":
        answer, thought = writer(blocks, repair="Your last answer" in user)
    else:
        answer, thought = {"terrain": terrain, "weather": weather, "trail": trail, "history": history,
                           "routes": routes, "synthesizer": synthesizer}[agent](blocks)
    return agent, answer, thought


def _failing(provider: str, agent: str) -> bool:
    fail = {item.strip() for item in os.environ.get("FAKE_LLM_FAIL", "").split(",") if item.strip()}
    return provider in fail or f"{provider}:{agent}" in fail


async def _pause() -> None:
    await asyncio.sleep(float(os.environ.get("FAKE_LLM_DELAY_S", "1.5")))


@app.post("/v1beta/models/{model_action}")
async def gemini(model_action: str, request: Request):
    body = await request.json()
    model = model_action.split(":")[0]
    user = body["contents"][-1]["parts"][0]["text"]
    agent, answer, thought = _answer(body["generationConfig"]["responseJsonSchema"]["properties"], user)
    await _pause()
    if _failing("gemini", agent):
        return JSONResponse({"error": {"code": 503, "message": "The model is overloaded (fake).",
                                       "status": "UNAVAILABLE"}}, status_code=503)
    return {
        "candidates": [{"content": {"role": "model", "parts": [
            {"text": thought, "thought": True},
            {"text": json.dumps(answer)},
        ]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": len(user) // 4, "candidatesTokenCount": 120, "thoughtsTokenCount": 60},
        "modelVersion": f"fake-{model}",
    }


@app.post("/v1/responses")
async def grok_responses(request: Request):
    body = await request.json()
    fmt = body["text"]["format"]
    user = next(m["content"] for m in body["input"] if m["role"] == "user")
    agent, answer, thought = _answer(fmt["schema"]["properties"], user)
    await _pause()
    if _failing("grok", agent):
        return JSONResponse({"code": "Service unavailable", "error": "Overloaded (fake)."}, status_code=503)
    return {
        "model": f"fake-{body['model']}",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": thought}], "status": "completed"},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": json.dumps(answer)}], "status": "completed"},
        ],
        "usage": {"input_tokens": len(user) // 4, "output_tokens": 140,
                  "output_tokens_details": {"reasoning_tokens": 80}},
    }


@app.post("/v1/chat/completions")
async def grok_chat(request: Request):
    body = await request.json()
    user = next(m["content"] for m in body["messages"] if m["role"] == "user")
    agent, answer, thought = _answer(body["response_format"]["json_schema"]["schema"]["properties"], user)
    await _pause()
    if _failing("grok", agent):
        return JSONResponse({"code": "Service unavailable", "error": "Overloaded (fake)."}, status_code=503)
    return {"model": f"fake-{body['model']}",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(answer), "reasoning_content": thought},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": 140}}
