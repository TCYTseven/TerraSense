"""A stand-in for the Gemini and xAI APIs, for tests and offline development. Not for demos.

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


def _find(blocks: list, key: str):
    return next((b for b in blocks if isinstance(b, dict) and key in b), None)


def _agent(properties: dict) -> str:
    if "place" in properties:
        return "terrain"
    if "modifier" in properties:
        return "weather"
    if "recommended_action" in properties:
        return "synthesizer"
    if "hiker" in properties:
        return "writer"
    return "trail"


def terrain(blocks: list) -> tuple[dict, str]:
    summary = _find(blocks, "hazard_zone") or {}
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


LEVELS = ["low", "moderate", "high", "extreme"]


def synthesizer(blocks: list) -> tuple[dict, str]:
    terrain_report = (_find(blocks, "hazard_zone") or {}).get("hazard_zone", {})
    weather_report = _find(blocks, "modifier") or {}
    trail_report = _find(blocks, "trail_name") or {}
    computed = _find(blocks, "final_confidence") or {}
    levels = [r.get("severity", "moderate") for r in (terrain_report, weather_report, trail_report)]
    severity = max(levels, key=LEVELS.index)
    action = "close" if severity in ("high", "extreme") and not computed.get("needs_review") else "monitor"
    miles = f"mile {trail_report.get('start_mile', 0):.1f} to {trail_report.get('end_mile', 0):.1f}"
    return {"severity": severity, "recommended_action": action,
            "summary": f"Debris flow risk on the {trail_report.get('trail_name')}, {miles}: {action} the segment.",
            "reasoning": [f"Reports: {', '.join(levels)}.", f"The top level is {severity}, so the action is {action}."]}, \
        f"Levels {levels}; taking the highest within range."


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
        answer, thought = {"terrain": terrain, "weather": weather, "trail": trail,
                           "synthesizer": synthesizer}[agent](blocks)
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
