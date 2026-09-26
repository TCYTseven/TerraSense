"""The contracts anything outside this process depends on.

Three seams, each tested against what actually consumes it:

- The ML model's input seam (`app/ml/probability.py`). Model B is rebuilt on the ML track, so
  what `score()` requires of it, and what it hands back, is pinned here.
- Each agent's output schema, as the two providers receive it. Gemini's `responseJsonSchema` and
  Grok's strict `json_schema` both reject `$ref`, a missing `type`, an open object, or a
  `required` list that does not name every property. A schema that drifts fails every call at
  runtime, so it is checked at build time instead.
- Every payload that leaves the process as JSON: tool results, agent payloads, `AgentEvent`
  (WebSocket `send_json`), `Run` (the stream, `GET /runs/{id}`, and the `agent_outputs` column),
  and `Advisory`. `json.dumps` takes no `default=` in any of those paths, so a numpy scalar, a
  datetime, or a NaN is a 500 rather than a rounding difference.
"""

import json
import sys
import types
from datetime import UTC, date, datetime

import httpx
import numpy as np
import pytest
import rasterio
from affine import Affine

from app.agents.pipeline import Pipeline
from app.agents.providers import GeminiProvider, GrokProvider, LLMRequest, llm_schema, make_providers
from app.agents.router import Router
from app.agents.schemas import AGENT_ORDER, AGENT_OUTPUTS, Advisory, Run
from app.agents.tools import RunContext
from app.ml import probability as prob
from app.runs import RunState
from app.weather import EXTRA_SERIES, _parse, get_hourly_rain

from .fake_llm import app as fake_llm

FIXTURE = "backend/fixtures/open_meteo_storm.json"
KEYS = {"GEMINI_API_KEY": "fake", "XAI_API_KEY": "fake",
        "GEMINI_BASE_URL": "http://fake-gemini", "XAI_BASE_URL": "http://fake-xai"}


# --- JSON-nativeness ---------------------------------------------------------------------------


def json_problems(value, path: str = "$") -> list[str]:
    """Every node json.dumps would refuse, or silently turn into something else."""
    problems: list[str] = []
    if value is None or isinstance(value, (bool, str)):
        return problems
    if isinstance(value, (int, float)):
        if type(value).__module__ == "numpy":
            problems.append(f"{path}: numpy scalar {type(value).__name__}")
        elif isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            problems.append(f"{path}: {value!r}; JSON has no NaN or Infinity")
        return problems
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                problems.append(f"{path}: non-string key {key!r}")
            problems += json_problems(item, f"{path}.{key}")
        return problems
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            problems += json_problems(item, f"{path}[{i}]")
        return problems
    if isinstance(value, (datetime, date)):
        problems.append(f"{path}: {type(value).__name__}; json.dumps raises without default=")
        return problems
    problems.append(f"{path}: {type(value).__module__}.{type(value).__name__} is not JSON-native")
    return problems


def assert_json_native(value, label: str) -> None:
    problems = json_problems(value, label)
    assert not problems, "\n".join(problems)
    json.dumps(value)  # the call every one of these paths actually makes


# --- the run every test in this module reads ----------------------------------------------------


@pytest.fixture(scope="module")
def finished_run(db_conn):
    """One full pipeline run against the fake providers, with its events."""
    import os

    from app.assessment import assess

    os.environ["FAKE_LLM_DELAY_S"] = "0"
    os.environ["OPEN_METEO_FIXTURE"] = FIXTURE
    rain = get_hourly_rain()
    assessment = assess(db_conn, rain=rain)
    ctx = RunContext(run_id="contracts", slug="mount-rainier", mountain="Mount Rainier",
                     peak=(46.8523, -121.7603), assessment=assessment, rain=rain,
                     rain_error=None)
    providers = make_providers(KEYS, httpx.ASGITransport(app=fake_llm))
    events: list = []

    async def emit(event):
        events.append(event)

    import asyncio

    result = asyncio.run(Pipeline(ctx, Router(providers, env=KEYS), providers, emit).run())
    assert result.status == "done", result.error
    return result, events, assessment


# --- 1. the ML model input seam -----------------------------------------------------------------


class _FakeModelBResult:
    """What step 17 first shipped: float64 on the susceptibility grid, plus its transform and CRS."""

    probability = np.full((4, 4), 0.5, dtype="float64")
    transform = Affine.translation(0, 0) @ Affine.scale(30, -30)
    crs = rasterio.crs.CRS.from_epsg(32610)


@pytest.fixture
def model_b():
    """app.ml.model_b, injected the way the real module would be imported, and recording its input."""
    seen: dict = {}
    module = types.ModuleType("app.ml.model_b")

    def run(rain):
        seen["rain"] = rain
        return _FakeModelBResult()

    module.run = run
    sys.modules["app.ml.model_b"] = module
    yield seen
    del sys.modules["app.ml.model_b"]


def test_score_reads_model_b_and_normalises_what_it_returns(model_b, monkeypatch):
    """Model B may hand back any float array and any CRS object; downstream needs float32 and a str."""
    monkeypatch.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    mapped = prob.score(get_hourly_rain())
    assert mapped.method == prob.MODEL_B_METHOD and not mapped.is_stand_in
    assert mapped.values.dtype == np.float32, "the tiler and the sampler both assume float32"
    assert isinstance(mapped.crs, str), "rasterio CRS objects do not survive into a layer's metadata"
    assert mapped.transform is _FakeModelBResult.transform


def test_model_b_receives_the_documented_rain_shape(model_b, monkeypatch):
    """What a Model B author may rely on. Adding a series must not move or rename any of it."""
    monkeypatch.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    prob.score(get_hourly_rain())
    rain = model_b["rain"]
    assert len(rain.times) == len(rain.precipitation_mm)
    assert 0 <= rain.now_index <= len(rain.times)
    assert rain.source in ("open-meteo", "fixture")
    assert isinstance(rain.total(-72, 0), float)


def test_the_extra_series_reach_model_b_aligned_with_the_hours(model_b):
    """A series of a different length would put at_now() on the wrong hour.

    Built here rather than read from the configured source: the storm fixture carries
    precipitation only, so reading it would assert nothing.
    """
    hours = 12
    full = _parse(
        {"hourly": {
            "time": [f"2026-09-25T{h:02d}:00" for h in range(hours)],
            "precipitation": [0.5] * hours,
            **{key: [float(i) for i in range(hours)] for key in EXTRA_SERIES},
        }},
        "fixture",
        datetime(2026, 9, 25, 4, tzinfo=UTC),
    )
    prob._from_model_b(sys.modules["app.ml.model_b"], full)
    rain = model_b["rain"]
    assert rain is full
    for name in EXTRA_SERIES.values():
        assert len(getattr(rain, name)) == len(rain.times), f"{name} is not aligned with the hours"
    assert rain.now_index == 4 and rain.at_now(rain.temperature_c) == 4.0


def test_score_uses_the_live_model_b_contract(monkeypatch):
    """The live Model B module is the source of truth once the ML track has shipped it."""
    monkeypatch.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    mapped = prob.score(get_hourly_rain())
    assert not mapped.is_stand_in and mapped.method == prob.MODEL_B_METHOD


def test_the_map_summary_is_json_native(monkeypatch):
    monkeypatch.setenv("OPEN_METEO_FIXTURE", FIXTURE)
    assert_json_native(prob.summarize(prob.score(get_hourly_rain()).values), "map_summary")


# --- 2. each agent's output schema, as a provider receives it ------------------------------------

ALLOWED_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
# Strict structured output rejects all of these. llm_schema() exists to remove them.
BANNED = {"$ref", "$defs", "$schema", "title", "default", "allOf", "oneOf", "anyOf", "definitions"}


def walk_schema(node, path: str) -> list[str]:
    problems: list[str] = []
    if isinstance(node, list):
        for i, item in enumerate(node):
            problems += walk_schema(item, f"{path}[{i}]")
        return problems
    if not isinstance(node, dict):
        return problems
    for key in BANNED & node.keys():
        problems.append(f"{path}: carries {key!r}, which strict mode rejects")
    kind = node.get("type")
    if kind is None and "enum" not in node:
        problems.append(f"{path}: has no 'type'")
    if isinstance(kind, list):
        problems.append(f"{path}: union type {kind}; strict mode takes one type")
    elif isinstance(kind, str) and kind not in ALLOWED_TYPES:
        problems.append(f"{path}: unknown type {kind!r}")
    if node.get("enum") == []:
        problems.append(f"{path}: empty enum")
    if kind == "object":
        props = node.get("properties")
        if not isinstance(props, dict):
            problems.append(f"{path}: object with no properties")
            return problems
        if node.get("additionalProperties") is not False:
            problems.append(f"{path}: not closed; additionalProperties must be false")
        if list(node.get("required", [])) != list(props):
            problems.append(f"{path}: required {node.get('required')} != properties {list(props)}")
        for name, sub in props.items():
            problems += walk_schema(sub, f"{path}.{name}")
    elif kind == "array":
        if "items" not in node:
            problems.append(f"{path}: array with no items schema")
        else:
            problems += walk_schema(node["items"], f"{path}[]")
    return problems


@pytest.mark.parametrize("agent", list(AGENT_OUTPUTS))
def test_the_wire_schema_is_what_strict_mode_accepts(agent):
    problems = walk_schema(llm_schema(AGENT_OUTPUTS[agent]), agent)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("agent", list(AGENT_OUTPUTS))
def test_both_providers_send_the_schema_unaltered(agent):
    """A provider that rewrites or drops the schema gets free-form prose back instead of JSON."""
    request = LLMRequest(system="s", user="u", schema=llm_schema(AGENT_OUTPUTS[agent]),
                         schema_name=f"{agent}_report")
    gemini = GeminiProvider({"GEMINI_API_KEY": "k"}).body(request)
    assert_json_native(gemini, f"gemini.body[{agent}]")
    assert gemini["generationConfig"]["responseJsonSchema"] == request.schema
    assert gemini["generationConfig"]["responseMimeType"] == "application/json"

    grok = GrokProvider({"XAI_API_KEY": "k"}).body(request)
    assert_json_native(grok, f"grok.body[{agent}]")
    fmt = grok["text"]["format"] if "text" in grok else grok["response_format"]["json_schema"]
    assert fmt["schema"] == request.schema and fmt.get("strict") is True


def test_the_synthesizer_schema_carries_the_whole_decision():
    """The one agent the advisory is built from: routes, response, and analysis all have to be there."""
    schema = llm_schema(AGENT_OUTPUTS["synthesizer"])
    props = schema["properties"]
    assert {"severity", "recommended_action", "avoid", "safe", "response", "analysis"} <= set(props)
    for side in ("avoid", "safe"):
        assert props[side]["minItems"] == props[side]["maxItems"] == 3, f"{side} must be exactly three"
        assert props[side]["items"]["type"] == "object"
    response = props["response"]["properties"]
    assert set(response["posture"]["enum"]) == {"all_clear", "watch", "advisory", "warning", "evacuate"}
    assert response["channels"]["items"]["enum"], "channels must be a closed list, not free text"


# --- 3. every payload that leaves the process ----------------------------------------------------


def test_tool_results_are_json_native(finished_run):
    """Tool results ride in the trace to the panel. numpy leaks in here first if anywhere does."""
    result, _, _ = finished_run
    for agent in AGENT_ORDER:
        for call in result.runs[agent].trace.tools:
            assert_json_native(call.result, f"{agent}.tool[{call.name}]")


def test_agent_payloads_are_json_native(finished_run):
    result, _, _ = finished_run
    for agent in AGENT_ORDER:
        assert_json_native(result.runs[agent].payload, f"{agent}.payload")


def test_every_agent_event_survives_websocket_send_json(finished_run):
    _, events, _ = finished_run
    assert events, "the run emitted no events"
    for event in events:
        assert_json_native(event.model_dump(mode="json"), f"event[{event.agent}/{event.status}]")


def test_the_advisory_round_trips_through_json(finished_run):
    result, _, _ = finished_run
    advisory = result.final.advisory
    dumped = advisory.model_dump(mode="json")
    assert_json_native(dumped, "advisory")
    assert Advisory.model_validate(json.loads(json.dumps(dumped))) == advisory


def test_the_advisory_route_numbers_are_the_maps_not_a_models(finished_run):
    """A caller renders these as data, so they have to match the scored catalog exactly."""
    result, _, assessment = finished_run
    catalog = {score.name: score for score in assessment.trail_scores}
    advisory = result.final.advisory
    assert len(advisory.avoid) == len(advisory.safe) == 3
    for route in advisory.avoid + advisory.safe:
        score = catalog[route.trail]  # KeyError here means a model invented a trail
        assert route.max_probability == score.max_probability
        assert route.share_at_high == score.share_high
        assert route.level == score.level
        assert route.length_mi == score.length_mi


def test_the_run_view_round_trips_the_way_the_agent_outputs_column_does(finished_run):
    """GET /runs/{id} answers from this column after a restart, so it has to survive jsonb."""
    result, events, _ = finished_run
    state = RunState(id="contracts", slug="mount-rainier", mountain_id="m",
                     mountain_name="Mount Rainier", peak=(46.8523, -121.7603))
    state.agents = {event.agent: event for event in events if event.status in ("done", "error")}
    state.advisory = result.final.advisory
    view = state.view()
    dumped = view.model_dump(mode="json")
    assert_json_native(dumped, "run")
    assert dumped["advisory"] is not None
    assert Run.model_validate(json.loads(json.dumps(dumped))) == view


def test_a_failed_run_carries_no_advisory_and_still_serializes():
    state = RunState(id="failed", slug="mount-rainier", mountain_id="m",
                     mountain_name="Mount Rainier", peak=(46.8523, -121.7603))
    state.status, state.phase = "error", "finished"
    state.error, state.failed_agent = "the provider went away", "weather"
    view = state.view()
    dumped = view.model_dump(mode="json")
    assert_json_native(dumped, "failed_run")
    assert dumped["advisory"] is None
    assert Run.model_validate(json.loads(json.dumps(dumped))) == view


# --- 4. the HTTP surface a caller generates a client from ----------------------------------------


def test_the_openapi_spec_documents_the_advisory():
    from fastapi.testclient import TestClient

    from app.main import app

    spec = TestClient(app).get("/openapi.json").json()
    for path in ("/runs/{run_id}", "/runs/{run_id}/advisory", "/mountains/{slug}/advisory"):
        assert path in spec["paths"], f"{path} is not in the spec, so no client can call it"
    schemas = spec["components"]["schemas"]
    for name in ("Advisory", "AdvisoryRoute", "AdvisoryResponse", "AdvisoryHazard",
                 "AdvisoryConditions", "AdvisoryModel", "AdvisoryAlert", "Run"):
        assert name in schemas, f"{name} is not generated, so a typed client cannot see it"
    advisory = schemas["Advisory"]["properties"]
    assert {"avoid", "safe", "response", "analysis", "hazard", "conditions", "model"} <= set(advisory)
