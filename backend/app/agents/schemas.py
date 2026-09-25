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

AgentName = Literal["terrain", "weather", "trail", "synthesizer", "writer"]
AgentStatus = Literal["waiting", "running", "done", "error"]
ProviderName = Literal["gemini", "grok"]
Tier = Literal["fast", "strong"]

AGENT_ORDER: tuple[AgentName, ...] = ("terrain", "weather", "trail", "synthesizer", "writer")
AGENT_LABELS: dict[AgentName, str] = {
    "terrain": "Terrain Analyst",
    "weather": "Weather Analyst",
    "trail": "Trail Analyst",
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


class SynthesisReport(AgentOutput):
    severity: RiskLevel = Field(description="The final level, within the range of the three reports.")
    recommended_action: Literal["monitor", "close"]
    summary: str = Field(description="One sentence for the ranger panel: hazard, trail and miles, action.")
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


class RunUpdate(BaseModel):
    """A stream message about the run as a whole. Agent messages are plain AgentEvents."""

    kind: Literal["run"] = "run"
    run: Run
