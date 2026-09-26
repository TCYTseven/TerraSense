"""What each agent must return, and the stream's event and trace shapes (step 20).

Two kinds of models live here:

- Agent outputs (TerrainReport ... AlertDraft): the JSON one model call must return. Every field
  is required and every object is closed, so a missing or extra field fails validation. Facts
  the code already knows (probabilities, miles, bypass numbers) are never asked of a model:
  the pipeline merges them into the event payload afterwards.
- Stream shapes (AgentEvent, AgentTrace, RouteDecision, ...): the API contract with
  frontend/lib/types.ts. Change both together.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import HazardType
from app.risk import RiskLevel

AgentName = Literal["terrain", "weather", "trail", "history", "routes", "synthesizer", "writer"]
AgentStatus = Literal["waiting", "running", "done", "error"]
ProviderName = Literal["gemini", "grok"]
Tier = Literal["fast", "strong"]

# Panel order. The five analysts run together in one fan-out; the Synthesizer waits for all of
# them, and the Alert Writer waits for the Synthesizer.
AGENT_ORDER: tuple[AgentName, ...] = (
    "terrain", "weather", "trail", "history", "routes", "synthesizer", "writer",
)
ANALYSTS: tuple[AgentName, ...] = ("terrain", "weather", "trail", "history", "routes")
AGENT_LABELS: dict[AgentName, str] = {
    "terrain": "Terrain Analyst",
    "weather": "Weather Analyst",
    "trail": "Trail Analyst",
    "history": "History Analyst",
    "routes": "Route Scout",
    "synthesizer": "Risk Synthesizer",
    "writer": "Alert Writer",
}

# The drivers an agent may cite for a hazard. The terrain ones come from the step 11 stack.
Driver = Literal[
    "slope_angle",
    "drainage_proximity",
    "sparse_vegetation",
    "soil_wetness",
    "concave_hollow",
    "past_landslides",
    "recent_rain",
    "forecast_rain",
]

Confidence = Annotated[float, Field(ge=0, le=1, description="0 to 1. Lower it when facts are thin or disagree.")]
Steps = Annotated[
    list[str],
    Field(min_length=2, max_length=4, description="2 to 4 short steps that show how you reached the answer, each citing a fact."),
]


class AgentOutput(BaseModel):
    """Base for what a model returns: closed objects, so extra fields fail too."""

    model_config = ConfigDict(extra="forbid")


class TerrainReport(AgentOutput):
    type: HazardType = Field(description="debris_flow when the zone is channelized, else landslide.")
    severity: RiskLevel
    drivers: list[Driver] = Field(min_length=1, max_length=4)
    confidence: Confidence
    place: str = Field(description="2 to 6 words locating the zone, using only names in the facts.")
    notes: str = Field(description="One or two plain sentences on where the zone is and what the ground is like.")
    reasoning: Steps


class WeatherReport(AgentOutput):
    modifier: Literal["worse", "stable", "better"]
    severity: RiskLevel = Field(description="The level the weather alone gives the zone.")
    confidence: Confidence
    note: str = Field(description="One or two plain sentences with the rain totals.")
    reasoning: Steps


class TrailReport(AgentOutput):
    severity: RiskLevel = Field(description="How dangerous the flagged miles are for hikers.")
    confidence: Confidence
    note: str = Field(description="One or two sentences: the flagged miles and how the bypass avoids them.")
    reasoning: Steps


class HistoryReport(AgentOutput):
    """What the landslide catalog says about ground like this on a day like this."""

    precedent: Literal["none", "weak", "moderate", "strong"] = Field(
        description="How strongly past events near the zone support today's rating."
    )
    severity: RiskLevel = Field(description="The level the record alone would give the zone.")
    confidence: Confidence
    note: str = Field(description="One or two sentences on the past events, or on their absence.")
    reasoning: Steps


class RouteNote(AgentOutput):
    """One trail from the catalog, with what its numbers mean for a hiker."""

    trail: str = Field(description="The trail's name, copied exactly from the catalog.")
    note: str = Field(description="One sentence citing that trail's numbers from the catalog.")


class RouteScan(AgentOutput):
    """The Route Scout's read of every mapped trail, not just the hero trail."""

    exposed: list[RouteNote] = Field(min_length=3, max_length=5,
                                     description="Trails carrying the most risk today, worst first.")
    clear: list[RouteNote] = Field(min_length=3, max_length=5,
                                   description="Trails that stay clear today and are worth a hike, cleanest first.")
    severity: RiskLevel = Field(description="How bad the trail network as a whole is today.")
    confidence: Confidence
    note: str = Field(description="One or two sentences on how the risk sits across the network.")
    reasoning: Steps


# --- the final advisory ------------------------------------------------------------------

Posture = Literal["all_clear", "watch", "advisory", "warning", "evacuate"]
POSTURES: tuple[Posture, ...] = ("all_clear", "watch", "advisory", "warning", "evacuate")

Priority = Literal["routine", "elevated", "urgent", "emergency"]
PRIORITIES: tuple[Priority, ...] = ("routine", "elevated", "urgent", "emergency")

# How the park tells people, quietest first. The newsletter reaches almost nobody in time, so it
# belongs to a routine posture; the emergency broadcast belongs only to an evacuation.
Channel = Literal[
    "newsletter",
    "website_banner",
    "trailhead_signage",
    "visitor_center_briefing",
    "ranger_radio",
    "social_media",
    "press_release",
    "emergency_broadcast",
]


class AvoidRoute(AgentOutput):
    """A route rangers should keep people off today."""

    trail: str = Field(description="The trail's name, copied exactly from the route catalog.")
    reason: str = Field(description="One sentence citing that trail's numbers from the catalog.")
    instead: str = Field(description="One sentence: the safer route or turn-around point to send hikers to.")


class SafeRoute(AgentOutput):
    """A route rangers can point people at today."""

    trail: str = Field(description="The trail's name, copied exactly from the route catalog.")
    reason: str = Field(description="One sentence citing that trail's numbers from the catalog.")
    caution: str = Field(description="One sentence of ordinary caution, such as mud, wind, or cold.")


class RangerResponse(AgentOutput):
    """What the park should actually do, scaled to the hazard."""

    posture: Posture = Field(
        description="all_clear: nothing to do. watch: keep an eye on it. advisory: tell people. "
                    "warning: close the ground and staff it. evacuate: get everyone off the mountain now."
    )
    priority: Priority = Field(description="How fast rangers must act: routine, elevated, urgent, emergency.")
    headline: str = Field(description="One short line a ranger reads first, under 90 characters.")
    channels: list[Channel] = Field(min_length=1, max_length=5,
                                    description="How to tell people, most important first.")
    actions: list[str] = Field(min_length=2, max_length=5,
                               description="2 to 5 concrete steps, each one a ranger can do today.")
    staffing: str = Field(description="One sentence: who goes where, or that no one needs to move.")
    timeline: str = Field(description="One sentence: when to act and when to look again.")
    escalate_if: str = Field(description="One sentence: the observation that moves this to the next posture.")


class LocationSynthesis(AgentOutput):
    """A decision for a summit that has weather and a cell classification, and no mapped trails."""

    severity: RiskLevel = Field(description="The final level, within the range of the analysts' reports.")
    recommended_action: Literal["monitor", "close"]
    summary: str = Field(description="One sentence: the mountain, the weather, and the action. Do not name a trail.")
    response: RangerResponse
    analysis: str = Field(description="One paragraph, 3 to 6 sentences, on the location, the classifier, and the weather.")
    coverage_note: str = Field(description="One sentence stating that no trails are mapped for this mountain.")
    reasoning: Steps


class SynthesisReport(AgentOutput):
    """The one final agent's answer: the call, the routes, and the response."""

    severity: RiskLevel = Field(description="The final level, within the range of the analysts' reports.")
    recommended_action: Literal["monitor", "close"]
    summary: str = Field(description="One sentence for the ranger panel: hazard, trail and miles, action.")
    avoid: list[AvoidRoute] = Field(min_length=3, max_length=3,
                                    description="Exactly three routes to keep hikers off today, worst first.")
    safe: list[SafeRoute] = Field(min_length=3, max_length=3,
                                  description="Exactly three routes that are safe today, best first.")
    response: RangerResponse
    analysis: str = Field(description="One paragraph, 3 to 6 sentences, on how the reports fit together.")
    reasoning: Steps


class AlertDraft(AgentOutput):
    ranger_body: str = Field(description="2 or 3 short sentences for rangers.")
    hiker: str = Field(description="One sentence, 25 words or fewer, naming the cause and the bypass.")
    what: str = Field(description="One sentence: the hazard type, the trail, and the mile range.")
    why: str = Field(description="One sentence: the main drivers and the rain.")
    how_to_avoid: str = Field(description="One sentence naming the bypass, or saying to turn back.")
    reasoning: Steps


AGENT_OUTPUTS: dict[AgentName, type[AgentOutput]] = {
    "terrain": TerrainReport,
    "weather": WeatherReport,
    "trail": TrailReport,
    "history": HistoryReport,
    "routes": RouteScan,
    "synthesizer": SynthesisReport,
    "writer": AlertDraft,
}


# --- Stream shapes (mirrored in frontend/lib/types.ts) ----------------------------------------


class RouteRule(BaseModel):
    """One rule the router checked, and what it decided."""

    rule: str  # "availability", "tier", "ambiguity", "stakes", "latency budget", "forced"
    verdict: ProviderName | None  # the provider the rule pointed to, or None when it changed nothing
    detail: str


class RouteDecision(BaseModel):
    provider: ProviderName
    model: str
    label: str  # "Gemini 3.8 Flash", "Grok 4.7"
    tier: Tier
    reason: str  # one sentence
    rules: list[RouteRule]
    fallback: list[ProviderName]  # tried in order if the chosen provider fails
    available: dict[str, bool]


class ToolCall(BaseModel):
    """A tool the agent's code ran before the model call. Tools return precomputed facts."""

    name: str
    args: dict[str, Any]
    result: Any
    ms: int


class Attempt(BaseModel):
    provider: ProviderName
    model: str
    ok: bool
    latency_ms: int
    error: str | None = None
    repair: bool = False  # this call re-asked the model after its answer failed a check


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


class AgentTrace(BaseModel):
    """Everything the reasoning panel shows for one agent."""

    route: RouteDecision
    tools: list[ToolCall] = []
    attempts: list[Attempt] = []
    thoughts: list[str] = []  # the provider's own reasoning summary, when it returns one
    reasoning: list[str] = []  # the steps the agent gave in its JSON
    checks: list[str] = []  # what the code did with the answer: merges, clamps, overrides, fallbacks
    output: dict[str, Any] | None = None  # the model's validated JSON, before the code merged facts
    usage: Usage | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    latency_ms: int | None = None


class AgentEvent(BaseModel):
    """One message on WS /runs/{run_id}/stream: an agent started, finished, or failed."""

    run_id: str
    agent: AgentName
    status: AgentStatus
    summary: str
    payload: dict[str, Any]
    trace: AgentTrace | None = None


# --- The advisory: the run's whole conclusion as one payload -----------------------------------
#
# GET /runs/{id}/advisory and GET /mountains/{slug}/advisory return this, and it rides on the Run
# so the stream and the panel get it without a second request. Every field is either a fact the
# code computed or a sentence an agent wrote about those facts: the route numbers, miles, and
# levels never come from a model. Mirrored in frontend/lib/types.ts.


class AdvisoryRoute(BaseModel):
    """One route on the avoid or the safe list, with the catalog numbers behind it."""

    trail: str
    level: RiskLevel
    max_probability: float
    share_at_high: float  # share of the walk at high or above
    length_mi: float | None
    elevation_gain_ft: int | None
    crosses_hazard_zone: bool
    km_to_hazard_zone: float | None
    is_hero_trail: bool
    reason: str  # the agent's sentence, citing the numbers above
    guidance: str  # where to go instead (avoid), or the day's caution (safe)


class AdvisoryResponse(BaseModel):
    """What the park does about it, scaled to the hazard."""

    posture: Posture
    posture_rank: int  # 0 all_clear to 4 evacuate, so a UI can sort or color without a lookup
    priority: Priority
    priority_rank: int  # 0 routine to 3 emergency
    recommended_action: Literal["monitor", "close"]
    headline: str
    channels: list[Channel]
    actions: list[str]
    staffing: str
    timeline: str
    escalate_if: str


class AdvisoryHazard(BaseModel):
    """The zone the advisory is about. None when no mile of the hero trail reaches high."""

    type: HazardType
    severity: RiskLevel
    place: str
    max_probability: float
    area_km2: float | None
    drivers: list[str]
    trail: str | None
    start_mile: float | None
    end_mile: float | None
    bypass_name: str | None
    bypass_added_mi: float | None
    bypass_added_ft: int | None


class AdvisoryConditions(BaseModel):
    """The weather the agents read. Fields are null when the source did not carry that series."""

    source: str
    as_of: datetime
    rain_past_72h_mm: float
    rain_next_24h_mm: float
    rain_past_72h_in: float
    rain_next_24h_in: float
    temp_now_c: float | None = None
    temp_min_next_72h_c: float | None = None
    temp_max_next_72h_c: float | None = None
    freeze_thaw_cycles_next_72h: int | None = None
    snowfall_next_72h_cm: float | None = None
    wind_max_next_24h_kmh: float | None = None
    soil_moisture_now: float | None = None
    freezing_level_now_m: float | None = None


class AdvisoryModel(BaseModel):
    """The ML prediction the agents treated as their source of truth."""

    method: str  # "model b", or the stand-in label while step 17 is out
    is_stand_in: bool
    note: str
    map_max: float | None
    map_mean: float | None
    share_at_high: float | None


class AgentVerdict(BaseModel):
    """One analyst's rating, so the panel can show where the agents agreed."""

    label: str
    severity: RiskLevel | None
    confidence: float | None
    provider: ProviderName | None
    model: str | None
    latency_ms: int | None


class AdvisoryAlert(BaseModel):
    """The Alert Writer's copy, for the panel and the hiker card."""

    title: str
    body: str
    hiker: str
    what: str
    why: str
    how_to_avoid: str


class Advisory(BaseModel):
    """Everything one run concluded, in one object."""

    run_id: str
    mountain_slug: str
    mountain: str
    generated_at: datetime
    severity: RiskLevel
    confidence: float
    needs_review: bool
    summary: str
    analysis: str
    hazard: AdvisoryHazard | None
    avoid: list[AdvisoryRoute]  # three routes to keep hikers off
    safe: list[AdvisoryRoute]  # three routes that are safe today
    response: AdvisoryResponse
    conditions: AdvisoryConditions | None
    model: AdvisoryModel
    alert: AdvisoryAlert
    agents: dict[AgentName, AgentVerdict]
    # What the code changed or refused in the agents' answers, so the panel can show the guard rails.
    checks: list[str] = []


# --- Runs (step 22), mirrored in frontend/lib/types.ts -----------------------------------------

RunStatus = Literal["running", "done", "error"]
RunPhase = Literal["starting", "scoring", "agents", "saving", "finished"]


class RainTotals(BaseModel):
    """The rain lines on the panel: past 72 hours and the next 24, from the run's Open-Meteo fetch."""

    source: str  # "open-meteo" or "fixture"
    as_of: datetime
    past_72h_mm: float
    next_24h_mm: float


class Run(BaseModel):
    """GET /runs/{run_id}, and the snapshot a stream sends on connect and at each phase."""

    id: str
    mountain_slug: str
    status: RunStatus
    phase: RunPhase
    message: str  # the status line under the agent rows
    started_at: datetime
    finished_at: datetime | None
    elapsed_s: float | None
    agents: dict[AgentName, AgentEvent]  # the latest event per agent; an agent not listed is waiting
    hazard_id: str | None
    severity: RiskLevel | None
    needs_review: bool | None
    method: str | None  # how the heat map was made, such as the stand-in label
    rain: RainTotals | None
    error: str | None
    failed_agent: AgentName | None
    # The run's whole conclusion. Null until the Alert Writer finishes, and on a failed run.
    advisory: Advisory | None = None


class RunUpdate(BaseModel):
    """A stream message about the run as a whole. Agent messages are plain AgentEvents."""

    kind: Literal["run"] = "run"
    run: Run
