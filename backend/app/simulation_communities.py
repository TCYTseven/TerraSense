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
        description=(
            '2–4 real settlements, each with a type prefix: "Village …", "Town …", or "Monastery …" '
            "(never a bare name)."
        )
    )
    alert: str = Field(
        description=(
            "One tight paragraph, at most 45 words. Relative geography only (downvalley, along the kora, below the trailhead). "
            "Who to warn and stay out of channels. Illustrative, not a forecast."
        )
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
Use real geography only. This is not an operational forecast.
Rules:
- places: 2–4 entries. Every name must start with Village, Town, or Monastery (e.g. Village Darchen,
  Monastery Zutulpuk). Pick settlements downvalley or along drainages from the sketched runout.
- alert: at most 45 words, active voice, two short sentences max. Relative WHERE (downvalley, east of the kora,
  below the release). Who to warn; stay out of channels. No filler, no AI talk, no trail mile markers.
- Mount Kailash: Village Darchen and kora-side monasteries when relevant."""


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
            places = [_label_place(name) for name in parsed.places]
            text = parsed.alert.strip()
            return _callout(text, places, t_s=0.0), True
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
            ["Village Darchen", "Monastery Drirapuk", "Town Purang (Burang)"],
            f"Warn Village Darchen at the kora trailhead and monasteries east along the inner circuit; debris from {trail} could reach channels below the north flank. "
            f"Keep pilgrims out of creek beds downvalley toward Town Purang.",
        ),
        "mount-rainier": (
            ["Village Longmire", "Town Ashford", "Village Paradise"],
            f"Alert Village Longmire in the Nisqually valley and Town Ashford at the gateway; sketched runout from {trail} follows drainages below the peak. "
            f"Clear channels near Village Paradise and keep visitors off low crossings.",
        ),
        "mount-everest": (
            ["Village Namche Bazaar", "Village Lukla", "Village Phakding"],
            f"Notify Village Namche Bazaar mid-valley and Village Phakding downstream; release above {trail} threatens Khumbu-side channels. "
            f"Brief airfield staff at Village Lukla and keep trekkers off creek paths.",
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


def _label_place(name: str) -> str:
    """Ensure list rows read Village … / Town … / Monastery …"""
    cleaned = name.strip()
    lower = cleaned.lower()
    if lower.startswith(("village ", "town ", "monastery ")):
        return cleaned
    if "monastery" in lower or "gompa" in lower or "temple" in lower:
        return f"Monastery {cleaned}"
    if "town" in lower or "bazaar" in lower or "city" in lower:
        return f"Town {cleaned}"
    return f"Village {cleaned}"


def _callout(text: str, places: list[str], *, t_s: float) -> dict:
    return {
        "id": CALLOUT_ID,
        "step_id": "release",
        "audience": "communities",
        "text": text,
        "places": places[:8],
        "t_s": t_s,
    }
