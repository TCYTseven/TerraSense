"""The agents' tools. Each returns precomputed facts for one run. None calls a model, scans a
raster, or draws trail geometry: the step 18 assessment, the step 19 bypass, and the route scan
already did that work, and the Open-Meteo response is fetched once per run.

An agent's code calls its tools before its model call and hands the results to the model as
JSON. Every call is recorded as a ToolCall, which the reasoning panel shows.

get_model_prediction is the one every agent calls first. It carries the ML model's output, which
is the run's source of truth: the agents read the map, they do not second-guess it. What they
add is everything the model never saw. The model's inputs are satellite terrain and land cover,
the rain series, and the hour of the year; it has no trail network, no closure history, no
catalog of past slides, and no idea where hikers actually walk. The analysts supply that, and
the Risk Synthesizer turns it into a decision.
"""

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app import packs
from app.assessment import Assessment, level_runs
from app.bypass import junctions_near, load_network
from app.config import REPO_ROOT
from app.history import historical_events
from app.ml.risk_inference import predict_location
from app.risk import HIGH_THRESHOLD
from app.trailscan import most_exposed, safest
from app.trailscan import summarize as summarize_network
from app.weather import HourlyRain, summarize

from .schemas import ToolCall

MM_PER_INCH = 25.4
KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084

# Guzzetti et al. (2008), the global minimum rainfall intensity-duration threshold for shallow
# landslides and debris flows: I = 2.20 * D^-0.44, with I in mm/h and D in hours. A total over
# D hours above threshold_mm(D) passes it. Given as a reference point, not a verdict.
GUZZETTI_A, GUZZETTI_B = 2.20, -0.44
JUNCTION_MARGIN_MI = 0.7  # junctions this close to the flagged miles help name the place
HISTORY_RADIUS_KM = 5.0
MOUNTAIN_HISTORY_RADIUS_KM = 30.0  # the History Analyst looks at the whole massif, not just the zone
CATALOG_SHORTLIST = 8  # how many trails each side of the route catalog's shortlists carries

METRICS_PATH = REPO_ROOT / "ml" / "artifacts" / "metrics.json"

MODEL_INPUTS = [
    "satellite terrain from the DEM: elevation, slope, aspect, curvature, distance to drainage, "
    "topographic wetness",
    "satellite land cover (ESA WorldCover)",
    "the hourly rain series around now",
]
MODEL_BLIND_SPOTS = [
    "where the trails go and which miles hikers actually walk",
    "past landslides in the catalog",
    "trail closures, bridges, and current conditions on the ground",
    "temperature, snow, wind, and freeze-thaw",
    "what a ranger should do about any of it",
]


def threshold_mm(hours: int) -> float:
    return round(GUZZETTI_A * hours**GUZZETTI_B * hours, 1)


@dataclass
class RunContext:
    """What one run knows before its agents start."""

    run_id: str
    slug: str
    mountain: str
    peak: tuple[float, float]  # lat, lon
    assessment: Assessment | None
    rain: HourlyRain | None
    rain_error: str | None = None
    elevation_m: int | None = None
    seed_level: str | None = None
    started: float = field(default_factory=time.perf_counter)

    @property
    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started


class ToolError(RuntimeError):
    """A tool had no facts to return, such as rain when Open-Meteo did not answer."""


def get_raster_summary(ctx: RunContext, mountain: str) -> dict:
    """The 72-hour map in numbers and the worst cluster the hero trail crosses."""
    a = ctx.assessment
    summary = {
        "mountain": ctx.mountain,
        "method": a.method,
        "method_note": (
            "Stand-in: the map is terrain susceptibility. Rain does not move it until the rain model lands."
            if a.probability.is_stand_in
            else "Model B: terrain susceptibility combined with past and forecast rain."
        ),
        "bins": {"low": "< 0.2", "moderate": "0.2 to 0.45", "high": "0.45 to 0.7", "extreme": "> 0.7"},
        "map": a.map_summary,
        "hazard_zone": None,
    }
    if a.zone is None or a.flagged is None:
        summary["note"] = "No hero trail segment reaches high, so there is no hazard zone."
        return summary
    zone, flagged = a.zone, a.flagged
    network = load_network(packs.network_path(ctx.slug))
    summary["hazard_zone"] = {
        "id": "hz_001",
        "level": zone.level,
        "max_probability": zone.max_probability,
        "mean_probability": zone.mean_probability,
        "area_km2": zone.area_km2,
        "centroid_lon_lat": list(zone.centroid),
        "trail": a.trail.name,
        "flagged_miles": {"start": flagged.start_mile, "end": flagged.end_mile,
                          "max_probability": flagged.max_probability, "level": flagged.level},
        "terrain": zone.terrain,
        "type_hint": zone.type_hint,
        "drivers_hint": list(zone.drivers_hint),
        "nearby_junctions": junctions_near(network, flagged.start_mile, flagged.end_mile, JUNCTION_MARGIN_MI)
        if network else [],
    }
    return summary


def get_trail_segments(ctx: RunContext, mountain: str) -> dict:
    """The hero trail's risk mile by mile, the flagged miles, and the bypass from step 19."""
    a = ctx.assessment
    facts = {
        "trail": a.trail.name,
        "length_mi": round(a.trail.segments[-1].end_mile, 2) if a.trail.segments else None,
        "direction": "Miles run clockwise from the Paradise trailhead (mile 0).",
        "risk_by_mile": level_runs(a.segments),
        "flagged": None,
        "bypass": None,
    }
    if a.flagged is None:
        return facts
    facts["flagged"] = {"start_mile": a.flagged.start_mile, "end_mile": a.flagged.end_mile,
                        "max_probability": a.flagged.max_probability, "level": a.flagged.level}
    bypass = a.bypass
    if bypass is None:
        facts["bypass"] = {"exists": False,
                           "advice": f"No trail runs around these miles. Turn back before mile {a.flagged.start_mile:.1f}."}
        return facts
    facts["bypass"] = {
        "exists": True,
        "name": bypass.name,
        "via": list(bypass.via),
        "leaves_at_mile": bypass.leaves_at_mile,
        "rejoins_at_mile": bypass.rejoins_at_mile,
        "length_km": bypass.length_km,
        "replaced_km": bypass.replaced_km,
        "added_km": bypass.added_km,
        "added_mi": round(bypass.added_km / KM_PER_MILE, 1),
        "added_elevation_m": bypass.added_elevation_m,
        "added_elevation_ft": int(round(bypass.added_elevation_m * FEET_PER_METER / 10) * 10),
        "worst_ground": {"max_probability": bypass.max_probability, "level": bypass.level},
    }
    return facts


def get_weather(ctx: RunContext, lat: float, lon: float) -> dict:
    """Rain around now at the trails' elevation, with the Guzzetti thresholds as reference."""
    if ctx.rain is None:
        raise ToolError(f"No rain data: {ctx.rain_error or 'Open-Meteo did not answer'}")
    rain = summarize(ctx.rain)
    facts = {
        "source": rain.source,
        "as_of": rain.as_of.isoformat(),
        "elevation_m": ctx.elevation_m if ctx.elevation_m is not None else 1650,
        "mm": {
            "past_24h": rain.past_24h_mm,
            "past_72h": rain.past_72h_mm,
            "past_7d": rain.past_7d_mm,
            "next_24h": rain.next_24h_mm,
            "next_72h": rain.next_72h_mm,
            "wettest_hour_next_72h": rain.max_hourly_next_72h_mm,
        },
        "inches": {
            "past_72h": round(rain.past_72h_mm / MM_PER_INCH, 2),
            "next_24h": round(rain.next_24h_mm / MM_PER_INCH, 2),
        },
        "guzzetti_threshold_mm": {"24h": threshold_mm(24), "72h": threshold_mm(72)},
        "past_72h_vs_threshold": round(rain.past_72h_mm / threshold_mm(72), 2),
        "next_72h_vs_threshold": round(rain.next_72h_mm / threshold_mm(72), 2),
        # Conditions the hazard model never saw. They do not move the map; they change what a
        # ranger tells a hiker, and freeze-thaw and soil moisture change how the ground behaves.
        "conditions": {
            "temperature_c_now": rain.temp_now_c,
            "temperature_c_next_72h": {"min": rain.temp_min_next_72h_c, "max": rain.temp_max_next_72h_c},
            "freeze_thaw_cycles_next_72h": rain.freeze_thaw_cycles_next_72h,
            "snowfall_cm_next_72h": rain.snowfall_next_72h_cm,
            "wind_kmh_max_next_24h": rain.wind_max_next_24h_kmh,
            "soil_moisture_top_7cm_now": rain.soil_moisture_now,
            "freezing_level_m_now": rain.freezing_level_now_m,
            "note": "Null means this run's weather source did not carry that series.",
        },
    }
    if rain.source == "fixture":
        facts["warning"] = "SYNTHETIC test storm from a saved file, not observed weather."
    return facts


def get_model_prediction(ctx: RunContext, mountain: str) -> dict:
    """The ML model's output: the run's source of truth, with what it saw and what it could not see.

    Every agent calls this first. The numbers here are the answer the map already gives. An agent
    never argues with them; it says what they mean for the part of the problem the model is blind
    to, which the blind_spots list names.
    """
    a = ctx.assessment
    card = _model_card(ctx.slug)
    facts = {
        "role": "SOURCE OF TRUTH. These numbers are the model's answer. Do not recompute or "
                "contradict them; explain what they mean.",
        "mountain": ctx.mountain,
        "method": a.method,
        "is_stand_in": a.probability.is_stand_in,
        "method_note": (
            "Stand-in: the map is terrain susceptibility alone. Rain does not move it until the rain "
            "model lands, so weight the Weather Analyst more heavily."
            if a.probability.is_stand_in
            else "Model B: terrain susceptibility combined with past and forecast rain."
        ),
        "inputs_the_model_saw": MODEL_INPUTS,
        "blind_spots": MODEL_BLIND_SPOTS,
        "bins": {"low": "< 0.2", "moderate": "0.2 to 0.45", "high": "0.45 to 0.7", "extreme": "> 0.7"},
        "high_threshold": HIGH_THRESHOLD,
        "map": a.map_summary,
        "model_card": card,
        "scored_at": a.computed_at.isoformat(),
        "hazard_zone": None,
        "hero_trail": {
            "trail": a.trail.name,
            "flagged_miles": None if a.flagged is None else {
                "start": a.flagged.start_mile, "end": a.flagged.end_mile,
                "max_probability": a.flagged.max_probability, "level": a.flagged.level,
            },
        },
        "trail_network": summarize_network(a.trail_scores),
    }
    # The legacy map remains the agent source of truth for the current HackGT trail workflow.
    # Carry the stricter classifier alongside it so every agent can see whether a production-grade
    # calibrated answer is actually available; this never turns an unavailable classifier into a
    # negative risk finding.
    # The point estimate is left out: at the summit it is one pixel of the map above, and an agent
    # would quote it as the mountain's chance.
    if ctx.rain is not None:
        classification = predict_location(
            ctx.peak[0], ctx.peak[1], rain_override=ctx.rain, probability_override=a.probability
        ).to_dict()
        for key in ("probability", "probability_source", "risk_level", "estimate"):
            classification.pop(key)
        facts["production_72h_classification"] = classification
    else:
        facts["production_72h_classification"] = {
            "state": "UNCERTAIN",
            "calibrated_probability": None,
            "reason_codes": ["FORECAST_UNAVAILABLE", "WEATHER_FEED_UNAVAILABLE"],
        }
    if a.zone is not None:
        facts["hazard_zone"] = {
            "id": "hz_001",
            "level": a.zone.level,
            "max_probability": a.zone.max_probability,
            "mean_probability": a.zone.mean_probability,
            "area_km2": a.zone.area_km2,
            "centroid_lon_lat": list(a.zone.centroid),
            "type_hint": a.zone.type_hint,
            "drivers_hint": list(a.zone.drivers_hint),
        }
    else:
        facts["note"] = "No hero trail segment reaches high, so the model found no hazard zone."
    return facts


def _model_card(slug: str) -> dict:
    """What the pack's metrics.json says about how the map was made. Empty when it is missing.

    A pack's card says trained: false and names the knowledge-driven index; only Rainier's
    ever reports an AUC.
    """
    metrics_path = packs.metrics_path(slug)
    if not metrics_path.exists():
        return {"note": "the pack's metrics.json is not written yet."}
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"note": f"the pack's metrics.json could not be read ({type(exc).__name__})."}
    return {
        "method": metrics.get("method"),
        "trained": metrics.get("trained"),
        "auc": metrics.get("auc"),
        "feature_weights": metrics.get("weights") or metrics.get("importance"),
        "note": metrics.get("note"),
    }


def get_trail_catalog(ctx: RunContext, mountain: str) -> dict:
    """Every mapped trail scored on the same map: the only routes anyone may name.

    The shortlists are the code's ranking, not a recommendation. An agent may pick from `trails`,
    but a route it names must appear there: the checks reject anything else.
    """
    scores = ctx.assessment.trail_scores
    if not scores:
        raise ToolError("No trail geometry for this mountain. Run python -m app.seed from backend/.")
    return {
        "rule": "Name only trails from this list, spelled exactly as they appear here.",
        "network": summarize_network(scores),
        "bins": {"low": "< 0.2", "moderate": "0.2 to 0.45", "high": "0.45 to 0.7", "extreme": "> 0.7"},
        "safe_ceiling": "A trail is safe_to_recommend when it is at least 0.8 km long and peaks below 0.35.",
        "most_exposed": [s.to_json() for s in most_exposed(scores, CATALOG_SHORTLIST)],
        "clearest": [s.to_json() for s in safest(scores, CATALOG_SHORTLIST)],
        "trails": [s.to_json() for s in scores],
    }


def get_historical_events(ctx: RunContext, lat: float, lon: float, radius_km: float = HISTORY_RADIUS_KM) -> dict:
    """Past catalog landslides within radius_km of a point."""
    near = []
    for event in historical_events(ctx.slug):
        distance = _km(lat, lon, event.lat, event.lon)
        if distance <= radius_km:
            near.append({"date": event.date, "category": event.category, "trigger": event.trigger,
                         "title": event.title, "km_away": round(distance, 1)})
    return {"radius_km": radius_km, "events": sorted(near, key=lambda e: e["km_away"]),
            "catalog_note": None if historical_events(ctx.slug) else "The landslide catalog is not downloaded yet."}


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def get_location_facts(ctx: RunContext, mountain: str) -> dict:
    """Summit location, the catalog's display color, and the cell classifier.

    Used when the mountain has no trail geometry. The classifier covers the Rainier training
    domain and returns UNCERTAIN outside it. That is a coverage gap, not a finding of safety.
    """
    prediction = predict_location(ctx.peak[0], ctx.peak[1], rain_override=ctx.rain).to_dict()
    return {
        "mountain": ctx.mountain,
        "latitude": ctx.peak[0],
        "longitude": ctx.peak[1],
        "elevation_m": ctx.elevation_m,
        "trails_mapped": False,
        "display_risk_level": ctx.seed_level,
        "display_risk_note": "Catalog color only. It is not a measurement and it is not the model's answer.",
        "cell_classification": prediction,
        "note": (
            "No trail lines and no terrain raster are stored for this mountain. "
            "Judge the summit from its location, this classification, and the weather. "
            "Do not invent a trail, a mile marker, or a bypass."
        ),
    }


TOOLS: dict[str, Callable[..., dict]] = {
    "get_model_prediction": get_model_prediction,
    "get_location_facts": get_location_facts,
    "get_raster_summary": get_raster_summary,
    "get_trail_segments": get_trail_segments,
    "get_trail_catalog": get_trail_catalog,
    "get_weather": get_weather,
    "get_historical_events": get_historical_events,
}


def call_tool(ctx: RunContext, name: str, **args) -> ToolCall:
    """Run one tool and record the call. ToolError propagates: the agent fails with it."""
    started = time.perf_counter()
    result = TOOLS[name](ctx, **args)
    return ToolCall(name=name, args=args, result=result, ms=round((time.perf_counter() - started) * 1000))
