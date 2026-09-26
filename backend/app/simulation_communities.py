"""One downvalley community alert for a runout simulation, from Gemini or Grok when configured."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.providers import LLMRequest, ProviderError, llm_schema, make_providers

logger = logging.getLogger(__name__)

CALLOUT_ID = "community-alert"


class CommunityAlertOutput(BaseModel):
    """Structured answer for the single simulation alert box."""

    model_config = ConfigDict(extra="forbid")

    places: list[str] = Field(
        description="Real villages, towns, monasteries, or camps within roughly 30 km downvalley that should be notified."
    )
    alert: str = Field(
        description="One short paragraph (under 75 words) for rangers: who to contact and why, illustrative not a forecast."
    )


def _terminal_point(frames: list[dict]) -> tuple[float | None, float | None]:
    if not frames:
        return None, None
    last = frames[-1]
    features = (last.get("geojson") or {}).get("features") or []
    if not features:
        return None, None
    geom = features[0].get("geometry") or {}
    coords = geom.get("coordinates")
    if geom.get("type") == "Polygon" and coords:
        ring = coords[0]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        return sum(lons) / len(lons), sum(lats) / len(lats)
    if geom.get("type") == "LineString" and coords:
        lon, lat = coords[-1]
        return float(lon), float(lat)
    return None, None


def _prompt_payload(
    mountain: dict[str, Any],
    point: dict,
    steps: list[dict],
    frames: list[dict],
    *,
    distance_m: float,
    drop_m: float,
) -> dict[str, Any]:
    term_lon, term_lat = _terminal_point(frames)
    trail_steps = [s for s in steps if s.get("kind") == "trail"]
    trail = trail_steps[0] if trail_steps else None
    return {
        "mountain": {
            "name": mountain.get("name"),
            "slug": mountain.get("slug"),
            "region": mountain.get("region"),
            "lat": mountain.get("lat"),
            "lon": mountain.get("lon"),
            "elevation_m": mountain.get("elevation_m"),
        },
        "release_trail": point.get("trail_name"),
        "release_lon": point.get("lon"),
        "release_lat": point.get("lat"),
        "runout_distance_km": round(distance_m / 1000, 2),
        "vertical_drop_m": round(drop_m),
        "terminal_lon": term_lon,
        "terminal_lat": term_lat,
        "trail_segment": {
            "name": (trail or {}).get("trail_name"),
            "start_mile": (trail or {}).get("start_mile"),
            "end_mile": (trail or {}).get("end_mile"),
        },
        "step_titles": [s.get("title") for s in steps[:8]],
    }


SYSTEM = """You help park rangers draft an illustrative debris-flow community alert for a demo app.
Use real geography only: name actual villages, towns, monasteries, or trailhead settlements in the
valleys below the mountain that could be affected if debris followed creek channels from the
sketched runout. This is not an operational forecast.
Rules:
- places: 2–5 real names, most relevant downvalley from the release.
- alert: one paragraph under 75 words, active voice, says who to notify and to stay out of channels.
- Do not mention AI, models, or mile markers on trails unless essential.
- If the mountain is Mount Kailash, include Darchen and other settlements on or below the kora route when appropriate."""


async def generate_community_callout(
    mountain: dict[str, Any],
    point: dict,
    steps: list[dict],
    frames: list[dict],
    *,
    distance_m: float,
    drop_m: float,
) -> tuple[dict, bool]:
    """Returns (callout dict, used_llm)."""
    payload = _prompt_payload(mountain, point, steps, frames, distance_m=distance_m, drop_m=drop_m)
    providers = make_providers()
    ordered = [providers["gemini"], providers["grok"]]
    for provider in ordered:
        if not provider.configured:
            continue
        request = LLMRequest(
            system=SYSTEM,
            user=json.dumps(payload, indent=2),
            schema=llm_schema(CommunityAlertOutput),
            schema_name="community_alert",
        )
        try:
            result = await provider.generate(request)
            parsed = CommunityAlertOutput.model_validate_json(result.text)
            text = parsed.alert.strip()
            if parsed.places and parsed.places[0].lower() not in text.lower():
                names = ", ".join(parsed.places[:5])
                text = f"{text} Settlements to alert: {names}."
            return _callout(text, parsed.places, t_s=0.0), True
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("simulation community alert via %s failed: %s", provider.name, exc)
            continue
    return fallback_community_callout(mountain, point, steps, distance_m=distance_m), False


def fallback_community_callout(
    mountain: dict[str, Any],
    point: dict,
    steps: list[dict],
    *,
    distance_m: float,
) -> dict:
    """One static box when no provider is configured."""
    slug = mountain.get("slug") or ""
    name = mountain.get("name") or "this peak"
    trail = point.get("trail_name") or "the steepest route"
    km = distance_m / 1000
    hints: dict[str, tuple[list[str], str]] = {
        "mount-kailash": (
            ["Darchen", "Hor Qu", "Purang (Burang)"],
            f"Illustrative runout from {trail} could send debris into kora-side channels. "
            f"Notify Darchen, Hor Qu, and settlements toward Purang (Burang); keep pilgrims out of creek beds below the release.",
        ),
        "mount-rainier": (
            ["Longmire", "Ashford", "Paradise"],
            f"Illustrative runout from {trail} (~{km:.1f} km sketched) could reach Nisqually and Tahoma Creek valleys. "
            f"Alert Longmire, Ashford, and Paradise-area staff; close affected trail segments and keep visitors out of channels.",
        ),
        "mount-everest": (
            ["Namche Bazaar", "Lukla", "Phakding"],
            f"Illustrative slope release above {trail} could affect Khumbu valley drainages. "
            f"Notify Namche Bazaar, Phakding, and Lukla-area lodges; keep trekkers off paths in active creek channels.",
        ),
    }
    places, alert = hints.get(
        slug,
        (
            ["Downvalley settlements"],
            f"Illustrative debris from {trail} on {name} could reach valley towns within ~{km:.1f} km of the sketched path. "
            f"Notify the nearest real villages and monasteries below the release; keep people out of creek channels.",
        ),
    )
    return _callout(alert, places, t_s=0.0)


def _callout(text: str, places: list[str], *, t_s: float) -> dict:
    return {
        "id": CALLOUT_ID,
        "step_id": "release",
        "audience": "communities",
        "text": text,
        "places": places[:8],
        "t_s": t_s,
    }
