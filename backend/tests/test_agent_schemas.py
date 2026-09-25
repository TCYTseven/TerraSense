"""Step 20: every agent output schema rejects a missing field, an extra field, and a bad value."""

import pytest
from pydantic import ValidationError

from app.agents.providers import llm_schema
from app.agents.schemas import AGENT_OUTPUTS, AgentEvent

VALID = {
    "terrain": {
        "type": "debris_flow",
        "severity": "high",
        "drivers": ["slope_angle", "drainage_proximity"],
        "confidence": 0.8,
        "place": "Below the 4th Crossing junction",
        "notes": "A steep drainage crosses the trail.",
        "reasoning": ["Peak 0.96 is extreme.", "61% of the zone is near a channel."],
    },
    "weather": {
        "modifier": "worse",
        "severity": "high",
        "confidence": 0.7,
        "note": "83 mm fell in 72 hours and 30 mm more is due.",
        "reasoning": ["Past rain is 3.4x the threshold.", "More rain is forecast."],
    },
    "trail": {
        "severity": "high",
        "confidence": 0.75,
        "note": "Miles 4.6 to 4.9 cross the zone; the Golden Gate Trail avoids them.",
        "reasoning": ["Three segments are high or extreme.", "The bypass saves 0.9 mi."],
    },
    "synthesizer": {
        "severity": "high",
        "recommended_action": "close",
        "summary": "Debris flow risk on the Skyline Trail, mile 4.6 to 4.9: close it.",
        "reasoning": ["All three reports say high.", "High calls for a closure."],
    },
    "writer": {
        "ranger_body": "Debris flow risk HIGH on the Skyline Trail, mile 4.6 to 4.9. Close the segment.",
        "hiker": "Heavy rain has loosened the slopes above the Skyline Trail, so take the Golden Gate Trail instead.",
        "what": "Debris flow zone on the Skyline Trail, mile 4.6 to 4.9.",
        "why": "Steep ground near a channel took 3.28 in of rain.",
        "how_to_avoid": "Take the Golden Gate Trail from mile 3.1 to mile 5.0.",
        "reasoning": ["Severity is high.", "The bypass exists."],
    },
}


@pytest.mark.parametrize("agent", list(AGENT_OUTPUTS))
def test_valid_example_passes(agent):
    AGENT_OUTPUTS[agent].model_validate(VALID[agent])


@pytest.mark.parametrize(("agent", "field"), [(a, f) for a, example in VALID.items() for f in example])
def test_missing_field_is_rejected(agent, field):
    example = {k: v for k, v in VALID[agent].items() if k != field}
    with pytest.raises(ValidationError):
        AGENT_OUTPUTS[agent].model_validate(example)


@pytest.mark.parametrize("agent", list(AGENT_OUTPUTS))
def test_extra_field_is_rejected(agent):
    with pytest.raises(ValidationError):
        AGENT_OUTPUTS[agent].model_validate({**VALID[agent], "invented": 1})


@pytest.mark.parametrize(("agent", "field", "value"), [
    ("terrain", "severity", "severe"),
    ("terrain", "drivers", ["gravity"]),
    ("terrain", "confidence", 1.4),
    ("weather", "modifier", "stormy"),
    ("synthesizer", "recommended_action", "evacuate"),
    ("writer", "reasoning", ["only one step"]),
])
def test_bad_value_is_rejected(agent, field, value):
    with pytest.raises(ValidationError):
        AGENT_OUTPUTS[agent].model_validate({**VALID[agent], field: value})


@pytest.mark.parametrize("agent", list(AGENT_OUTPUTS))
def test_llm_schema_is_closed_and_flat(agent):
    schema = llm_schema(AGENT_OUTPUTS[agent])
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text and "'title'" not in text
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])


def test_agent_event_trace_is_optional():
    event = AgentEvent(run_id="r1", agent="terrain", status="running", summary="Reading the map.", payload={})
    assert event.trace is None
