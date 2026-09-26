"""Every agent output schema rejects a missing field, an extra field, and a bad value."""

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
    "history": {
        "precedent": "weak",
        "severity": "high",
        "confidence": 0.4,
        "note": "The catalog holds no recorded slide within 30 km, which is an absence of record.",
        "reasoning": ["No catalog event inside the radius.", "An empty record cannot lower the level."],
    },
    "routes": {
        "exposed": [
            {"trail": "North Puyallup Trail", "note": "88% of it sits at high or above."},
            {"trail": "Van Trump Trail", "note": "81% of it sits at high or above."},
            {"trail": "Glacier Basin Trail", "note": "68% of it sits at high or above."},
        ],
        "clear": [
            {"trail": "Rampart Ridge Trail", "note": "It peaks at 0.17, in the low band."},
            {"trail": "Sunrise Rim", "note": "It peaks at 0.34, in the moderate band."},
            {"trail": "Dead Horse Creek Trail", "note": "It peaks at 0.38, in the moderate band."},
        ],
        "severity": "extreme",
        "confidence": 0.7,
        "note": "56 of 67 trails reach high or above today.",
        "reasoning": ["The worst trail peaks at 1.0.", "Two trails clear the safe ceiling."],
    },
    "synthesizer": {
        "severity": "high",
        "recommended_action": "close",
        "summary": "Debris flow risk on the Skyline Trail, mile 4.6 to 4.9: close it.",
        "avoid": [
            {"trail": "Skyline Trail", "reason": "It crosses the zone at mile 4.6 to 4.9.",
             "instead": "Send hikers to the Rampart Ridge Trail."},
            {"trail": "North Puyallup Trail", "reason": "88% of it is at high or above.",
             "instead": "Send hikers to the Sunrise Rim."},
            {"trail": "Van Trump Trail", "reason": "81% of it is at high or above.",
             "instead": "Send hikers to the Rampart Ridge Trail."},
        ],
        "safe": [
            {"trail": "Rampart Ridge Trail", "reason": "It peaks at 0.17, in the low band.",
             "caution": "Expect mud underfoot after the rain."},
            {"trail": "Sunrise Rim", "reason": "It peaks at 0.34, in the moderate band.",
             "caution": "Least exposed today, not safe ground."},
            {"trail": "Dead Horse Creek Trail", "reason": "It peaks at 0.38, in the moderate band.",
             "caution": "Least exposed today, not safe ground."},
        ],
        "response": {
            "posture": "warning",
            "priority": "urgent",
            "headline": "Close Skyline Trail mile 4.6 to 4.9 for debris flow.",
            "channels": ["trailhead_signage", "website_banner"],
            "actions": ["Close the Skyline Trail from mile 4.6 to 4.9.",
                        "Brief the desk so staff can redirect hikers."],
            "staffing": "One ranger at the Paradise trailhead through the afternoon.",
            "timeline": "Close it today and look again after the next rain.",
            "escalate_if": "Fresh debris appears on these miles.",
        },
        "analysis": "The analysts agree at high. The zone crosses the hero trail. The bypass is itself "
                    "exposed, so the closure stands.",
        "reasoning": ["All five reports say high.", "High calls for a closure."],
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
    ("history", "precedent", "overwhelming"),
    ("synthesizer", "recommended_action", "evacuate"),
    ("synthesizer", "avoid", []),  # the advisory always carries exactly three
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

    def closed(node):
        """Every nested object is closed too: the Synthesizer's routes and response are objects."""
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert node["required"] == list(node["properties"])
            for value in node.values():
                closed(value)
        elif isinstance(node, list):
            for item in node:
                closed(item)

    closed(schema)


@pytest.mark.parametrize("side", ["avoid", "safe"])
def test_synthesizer_needs_exactly_three_routes(side):
    """Two is not an advisory and four does not fit the panel: the schema pins it at three."""
    example = VALID["synthesizer"]
    for count in (2, 4):
        routes = (example[side] * 2)[:count]
        with pytest.raises(ValidationError):
            AGENT_OUTPUTS["synthesizer"].model_validate({**example, side: routes})


def test_ranger_response_rejects_an_invented_channel():
    response = {**VALID["synthesizer"]["response"], "channels": ["carrier_pigeon"]}
    with pytest.raises(ValidationError):
        AGENT_OUTPUTS["synthesizer"].model_validate({**VALID["synthesizer"], "response": response})


def test_agent_event_trace_is_optional():
    event = AgentEvent(run_id="r1", agent="terrain", status="running", summary="Reading the map.", payload={})
    assert event.trace is None
