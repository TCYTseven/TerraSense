"""The guard rails on the Risk Synthesizer: posture, priority, channels, and the route shortlists.

These are the checks that stand between a model's answer and what a ranger reads, so they are
tested on their own rather than only through a run. No database and no model: pure policy.
"""

import pytest

from app.agents import advisory as guards
from app.agents.schemas import AvoidRoute, RangerResponse, SafeRoute
from app.trailscan import TrailScore

LOUDEST = RangerResponse(
    posture="evacuate",
    priority="emergency",
    headline="Everyone off the mountain now.",
    channels=["emergency_broadcast", "press_release", "newsletter"],
    actions=["Clear the trail.", "Call the sheriff."],
    staffing="Every ranger on shift.",
    timeline="Now.",
    escalate_if="Nothing louder exists.",
)


def score(name: str, peak: float, *, share: float = 0.0, km: float = 2.0, crosses: bool = False) -> TrailScore:
    level = "extreme" if peak > 0.7 else "high" if peak >= 0.45 else "moderate" if peak >= 0.2 else "low"
    return TrailScore(trail_id=name, name=name, length_km=3.0, elevation_gain_m=200, max_probability=peak,
                      mean_probability=peak / 2, share_high=share, level=level, worst_point=(0.0, 0.0),
                      is_hero=False, km_to_zone=km, crosses_zone=crosses)


@pytest.fixture
def catalog() -> list[TrailScore]:
    """A mountain with clear ground at one end and extreme ground at the other."""
    return [
        score("Doom Ridge Trail", 0.98, share=0.9, km=0.0, crosses=True),
        score("Slide Gully Trail", 0.95, share=0.8),
        score("Wet Bowl Trail", 0.80, share=0.6),
        score("Middling Trail", 0.40),
        score("Quiet Creek Trail", 0.18),
        score("Meadow Loop Trail", 0.09),
        score("Low Bench Trail", 0.05),
    ]


# --- posture ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("severity", "action", "expected"), [
    ("extreme", "close", "evacuate"),   # the only case that may clear the mountain
    ("extreme", "monitor", "advisory"),  # not closing it means not evacuating it
    ("high", "close", "warning"),
    ("high", "monitor", "advisory"),
    ("moderate", "close", "advisory"),
    ("low", "close", "watch"),           # nothing at low speaks louder than a watch
])
def test_posture_cannot_outrun_the_severity(severity, action, expected):
    clamped, _ = guards.clamp_response(LOUDEST, severity, action, needs_review=False)
    assert clamped.posture == expected


def test_disagreement_caps_the_posture_at_an_advisory():
    """Analysts two levels apart means the run is not sure, and not sure does not clear a mountain."""
    clamped, checks = guards.clamp_response(LOUDEST, "extreme", "close", needs_review=True)
    assert clamped.posture == "advisory"
    assert any("disagree" in check for check in checks)


def test_every_clamp_is_recorded():
    """A ranger reading the panel can see what the code overrode, not just the result."""
    _, checks = guards.clamp_response(LOUDEST, "low", "monitor", needs_review=False)
    assert any("posture" in check for check in checks)
    assert any("priority" in check for check in checks)
    assert any("Dropped" in check for check in checks)


# --- priority and channels --------------------------------------------------------------------


def test_priority_follows_the_posture():
    """The loudest answer lands on the top of the band the severity allows, and drags priority with it."""
    clamped, _ = guards.clamp_response(LOUDEST, "low", "monitor", needs_review=False)
    assert clamped.posture == "watch" and clamped.priority == "elevated"
    quiet, _ = guards.clamp_response(LOUDEST.model_copy(update={"posture": "all_clear"}),
                                     "low", "monitor", needs_review=False)
    assert quiet.posture == "all_clear" and quiet.priority == "routine"


@pytest.mark.parametrize("severity", ["low", "moderate", "high"])
def test_the_emergency_broadcast_belongs_to_an_evacuation_alone(severity):
    clamped, _ = guards.clamp_response(LOUDEST, severity, "close", needs_review=False)
    assert "emergency_broadcast" not in clamped.channels


def test_a_warning_reaches_the_trailhead():
    quiet = LOUDEST.model_copy(update={"channels": ["newsletter"]})
    clamped, checks = guards.clamp_response(quiet, "high", "close", needs_review=False)
    assert clamped.posture == "warning"
    assert guards.REQUIRED_SIGNAGE in clamped.channels
    assert any("hikers reach it" in check for check in checks)


def test_the_newsletter_is_never_the_only_word_on_an_advisory():
    quiet = LOUDEST.model_copy(update={"channels": ["newsletter"]})
    clamped, _ = guards.clamp_response(quiet, "moderate", "close", needs_review=False)
    assert clamped.posture == "advisory" and clamped.channels != ["newsletter"]


def test_a_calm_mountain_still_fills_the_avoid_list():
    """Three routes a side always, even when nothing on the map is dangerous."""
    calm = [score(f"Trail {n}", 0.02 + n / 100) for n in range(6)]
    pool = guards.avoid_pool(calm)
    assert len(pool) >= 3
    avoid_routes, safe_routes = guards.fallback_routes(calm, "Trail 0", None)
    assert len(avoid_routes) == len(safe_routes) == 3
    assert guards.route_problems(avoid_routes, safe_routes, calm) == []


def test_a_quiet_day_stays_quiet():
    """The newsletter is the right answer sometimes, and the policy leaves it alone."""
    calm = LOUDEST.model_copy(update={"posture": "all_clear", "priority": "routine",
                                      "channels": ["newsletter"]})
    clamped, checks = guards.clamp_response(calm, "low", "monitor", needs_review=False)
    assert clamped.posture == "all_clear" and clamped.channels == ["newsletter"]
    assert clamped.priority == "routine" and checks == []


# --- routes -----------------------------------------------------------------------------------


def avoid(*names):
    return [AvoidRoute(trail=n, reason="r", instead="i") for n in names]


def safe(*names):
    return [SafeRoute(trail=n, reason="r", caution="c") for n in names]


def test_a_good_set_has_no_problems(catalog):
    chosen_avoid = [s.name for s in guards.avoid_pool(catalog)[:3]]
    chosen_safe = [s.name for s in guards.safe_pool(catalog)[:3]]
    assert guards.route_problems(avoid(*chosen_avoid), safe(*chosen_safe), catalog) == []


def test_an_unmapped_trail_is_rejected(catalog):
    problems = guards.route_problems(avoid("Mordor Ridge Trail", "Doom Ridge Trail", "Slide Gully Trail"),
                                     safe("Meadow Loop Trail", "Low Bench Trail", "Quiet Creek Trail"), catalog)
    assert len(problems) == 1 and "not a trail in the route catalog" in problems[0]


def test_a_clear_trail_cannot_be_called_dangerous(catalog):
    """The avoid list only takes trails the map actually flags."""
    problems = guards.route_problems(avoid("Low Bench Trail", "Doom Ridge Trail", "Slide Gully Trail"),
                                     safe("Meadow Loop Trail", "Quiet Creek Trail", "Middling Trail"), catalog)
    assert any("most_exposed shortlist" in p for p in problems)


def test_a_dangerous_trail_cannot_be_called_safe(catalog):
    problems = guards.route_problems(avoid("Doom Ridge Trail", "Slide Gully Trail", "Wet Bowl Trail"),
                                     safe("Doom Ridge Trail", "Meadow Loop Trail", "Low Bench Trail"), catalog)
    assert any("clearest shortlist" in p or "also on the avoid list" in p for p in problems)


def test_the_same_trail_twice_is_rejected(catalog):
    problems = guards.route_problems(avoid("Doom Ridge Trail", "Doom Ridge Trail", "Slide Gully Trail"),
                                     safe("Meadow Loop Trail", "Low Bench Trail", "Quiet Creek Trail"), catalog)
    assert any("already on the avoid list" in p for p in problems)


def test_a_name_survives_case_and_a_missing_word(catalog):
    problems = guards.route_problems(avoid("the doom ridge", "SLIDE GULLY TRAIL", "Wet Bowl Trail"),
                                     safe("meadow loop", "Low Bench", "quiet creek trail"), catalog)
    assert problems == []


def test_the_fallback_fills_three_a_side_from_the_facts(catalog):
    """When no model answer survives, the code still hands a ranger three and three."""
    avoid_routes, safe_routes = guards.fallback_routes(catalog, "Doom Ridge Trail", "Middling Trail")
    assert len(avoid_routes) == len(safe_routes) == 3
    assert guards.route_problems(avoid_routes, safe_routes, catalog) == []
    assert all(route.reason and route.instead for route in avoid_routes)
    assert all(route.reason and route.caution for route in safe_routes)


def test_the_safe_list_says_so_when_safety_is_only_relative():
    """On a saturated map, every caution has to say least exposed rather than safe."""
    saturated = [score(f"Trail {n}", 0.6 + n / 100, share=0.5) for n in range(8)]
    _, safe_routes = guards.fallback_routes(saturated, "Trail 0", None)
    assert len(safe_routes) == 3
    assert all("not safe ground" in route.caution for route in safe_routes)


def test_the_fallback_response_is_never_louder_than_the_policy_allows():
    for severity in ("low", "moderate", "high", "extreme"):
        for action in ("monitor", "close"):
            response = guards.fallback_response(severity, action, needs_review=False,
                                                trail_name="Doom Ridge Trail", miles="mile 1.0 to 2.0")
            clamped, checks = guards.clamp_response(response, severity, action, needs_review=False)
            assert clamped == response, f"{severity}/{action} needed clamping: {checks}"
