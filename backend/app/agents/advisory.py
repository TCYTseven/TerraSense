"""The guard rails on the Risk Synthesizer's answer, and the advisory the API returns.

The Synthesizer is the one agent that decides anything: the final severity, the three routes to
keep hikers off, the three that are safe today, and what the park actually does about it. That is
a lot of trust for a model, so code checks it before anyone sees it:

- Routes. A route must be one the code shortlisted from the scored catalog (app/trailscan.py).
  The model chooses which three; it cannot name a trail the map does not support, invent a path,
  or put the same trail on both lists. A wrong name comes back as a check and the agent tries
  again with the problems listed.
- Posture and priority. The response has to match the severity the run actually reached.
  "Everyone off the mountain" needs an extreme rating and a close recommendation, and a run whose
  analysts disagree by two levels cannot go past an advisory no matter what the model wrote.
  Code clamps rather than fails: a posture that is too loud is turned down and the change is
  recorded in the trace, so the panel shows what the code overrode.
- Channels. How loudly the park speaks follows the posture. The emergency broadcast belongs to an
  evacuation and nothing else; the newsletter, which nobody reads in time, cannot be the only way
  a warning goes out.

When the model fails every attempt, fallback() builds the same advisory from the facts alone, so
the endpoint always answers with something a ranger can act on.
"""

from app.risk import BIN_EDGES, RiskLevel
from app.trailscan import TrailScore, most_exposed, relative_only, resolve, safest

from .schemas import (
    PRIORITIES,
    POSTURES,
    AdvisoryRoute,
    AvoidRoute,
    Channel,
    Posture,
    Priority,
    RangerResponse,
    SafeRoute,
)

# How many trails the code shortlists on each side. The Synthesizer picks three from each.
AVOID_POOL = 10
SAFE_POOL = 10
# A trail below the moderate bin is ground the map says nothing against, so it cannot be a route
# to avoid however the mountain ranks. On a genuinely calm day nothing clears this and the pool
# falls back to the worst three, with the advisory's own numbers showing how mild they are.
AVOID_FLOOR = BIN_EDGES[0]
ROUTES_PER_SIDE = 3

# The loudest posture each severity may reach, and the quietest that does it justice. A run that
# needs review, or that recommends monitoring rather than closing, is capped separately below.
POSTURE_RANGE: dict[RiskLevel, tuple[Posture, Posture]] = {
    "low": ("all_clear", "watch"),
    "moderate": ("watch", "advisory"),
    "high": ("advisory", "warning"),
    "extreme": ("warning", "evacuate"),
}
# Closing the trail is what separates telling people from moving them. Without it, an advisory is
# as far as the park goes.
MONITOR_CEILING: Posture = "advisory"
# Analysts two levels apart means the run is not sure. Not sure does not clear a mountain.
REVIEW_CEILING: Posture = "advisory"

PRIORITY_RANGE: dict[Posture, tuple[Priority, Priority]] = {
    "all_clear": ("routine", "routine"),
    "watch": ("routine", "elevated"),
    "advisory": ("elevated", "urgent"),
    "warning": ("urgent", "emergency"),
    "evacuate": ("emergency", "emergency"),
}

# A channel nobody may use below this posture.
CHANNEL_FLOOR: dict[str, Posture] = {
    "press_release": "warning",
    "emergency_broadcast": "evacuate",
    "ranger_radio": "advisory",
}
# From this posture up, the park has to put it where hikers will actually see it.
SIGNAGE_FROM: Posture = "warning"
REQUIRED_SIGNAGE: Channel = "trailhead_signage"
QUIET_CHANNELS: tuple[Channel, ...] = ("newsletter", "website_banner", "visitor_center_briefing")

POSTURE_WORDS: dict[Posture, str] = {
    "all_clear": "All clear",
    "watch": "Watch",
    "advisory": "Advisory",
    "warning": "Warning",
    "evacuate": "Evacuate",
}


def posture_rank(posture: Posture) -> int:
    return POSTURES.index(posture)


def priority_rank(priority: Priority) -> int:
    return PRIORITIES.index(priority)


def _clamp(value: str, low: str, high: str, order: tuple[str, ...]) -> str:
    return order[min(max(order.index(value), order.index(low)), order.index(high))]


# --- route checks -----------------------------------------------------------------------------


def avoid_pool(scores: list[TrailScore]) -> list[TrailScore]:
    """The trails a ranger may be told to avoid: exposed enough that the map supports it.

    Ranking alone is not enough. On a small network the ten worst trails can include ground that
    never leaves the low bin, and "avoid the Low Bench Trail, which peaks at 0.05" is advice the
    map does not support. Below the floor the pool falls back to the worst three, so the advisory
    always has three routes and their own numbers say how mild they are.
    """
    ranked = most_exposed(scores, AVOID_POOL)
    flagged = [s for s in ranked if s.max_probability >= AVOID_FLOOR]
    if len(flagged) >= ROUTES_PER_SIDE:
        return flagged
    return ranked[:max(ROUTES_PER_SIDE, len(flagged))]


def safe_pool(scores: list[TrailScore]) -> list[TrailScore]:
    return safest(scores, SAFE_POOL)


def route_problems(avoid: list[AvoidRoute], safe: list[SafeRoute], scores: list[TrailScore]) -> list[str]:
    """What is wrong with the routes the model picked, phrased so it can fix them and try again."""
    problems: list[str] = []
    allowed_avoid = {s.name for s in avoid_pool(scores)}
    allowed_safe = {s.name for s in safe_pool(scores)}
    chosen_avoid: list[str] = []
    chosen_safe: list[str] = []

    for index, route in enumerate(avoid):
        match = resolve(scores, route.trail)
        if match is None:
            problems.append(f"avoid.{index}.trail: {route.trail!r} is not a trail in the route catalog.")
        elif match.name not in allowed_avoid:
            problems.append(
                f"avoid.{index}.trail: {match.name} is not on the most_exposed shortlist, so the map does "
                f"not support avoiding it. Pick one of: {', '.join(sorted(allowed_avoid))}."
            )
        elif match.name in chosen_avoid:
            problems.append(f"avoid.{index}.trail: {match.name} is already on the avoid list.")
        else:
            chosen_avoid.append(match.name)

    for index, route in enumerate(safe):
        match = resolve(scores, route.trail)
        if match is None:
            problems.append(f"safe.{index}.trail: {route.trail!r} is not a trail in the route catalog.")
        elif match.name not in allowed_safe:
            problems.append(
                f"safe.{index}.trail: {match.name} is not on the clearest shortlist, so the map does not "
                f"support calling it safe. Pick one of: {', '.join(sorted(allowed_safe))}."
            )
        elif match.name in chosen_safe:
            problems.append(f"safe.{index}.trail: {match.name} is already on the safe list.")
        elif match.name in chosen_avoid:
            problems.append(f"safe.{index}.trail: {match.name} is also on the avoid list.")
        else:
            chosen_safe.append(match.name)
    return problems


def merge_route(score: TrailScore, reason: str, guidance: str) -> AdvisoryRoute:
    """One advisory route: the agent's two sentences over the catalog's numbers."""
    return AdvisoryRoute(
        trail=score.name,
        level=score.level,
        max_probability=score.max_probability,
        share_at_high=score.share_high,
        length_mi=score.length_mi,
        elevation_gain_ft=score.gain_ft,
        crosses_hazard_zone=score.crosses_zone,
        km_to_hazard_zone=score.km_to_zone,
        is_hero_trail=score.is_hero,
        reason=reason.strip(),
        guidance=guidance.strip(),
    )


# --- response checks --------------------------------------------------------------------------


def clamp_response(response: RangerResponse, severity: RiskLevel, action: str,
                   needs_review: bool) -> tuple[RangerResponse, list[str]]:
    """The response the park may actually issue, and every change the code made to get there."""
    checks: list[str] = []
    low, high = POSTURE_RANGE[severity]
    posture: Posture = _clamp(response.posture, low, high, POSTURES)  # type: ignore[assignment]
    if posture != response.posture:
        checks.append(f"Moved the posture from {response.posture} to {posture}: a {severity} rating sits "
                      f"between {low} and {high}.")
    if action == "monitor" and posture_rank(posture) > posture_rank(MONITOR_CEILING):
        checks.append(f"Turned the posture down from {posture} to {MONITOR_CEILING}: the action is to monitor "
                      "the segment, not to close it.")
        posture = MONITOR_CEILING
    if needs_review and posture_rank(posture) > posture_rank(REVIEW_CEILING):
        checks.append(f"Turned the posture down from {posture} to {REVIEW_CEILING}: the analysts disagree by "
                      "two levels, so the alert goes out as an advisory to confirm on site.")
        posture = REVIEW_CEILING

    plow, phigh = PRIORITY_RANGE[posture]
    priority: Priority = _clamp(response.priority, plow, phigh, PRIORITIES)  # type: ignore[assignment]
    if priority != response.priority:
        checks.append(f"Moved the priority from {response.priority} to {priority}: a {posture} posture runs "
                      f"between {plow} and {phigh}.")

    channels, dropped = _clamp_channels(list(response.channels), posture)
    if dropped:
        checks.append(f"Dropped {', '.join(dropped)}: not used below a {posture} posture.")
    if posture_rank(posture) >= posture_rank(SIGNAGE_FROM) and REQUIRED_SIGNAGE not in channels:
        channels.insert(0, REQUIRED_SIGNAGE)
        checks.append(f"Added {REQUIRED_SIGNAGE}: at {posture} the closure has to be where hikers reach it.")
    if posture_rank(posture) >= posture_rank("advisory") and set(channels) <= {"newsletter"}:
        channels.insert(0, "website_banner")
        checks.append("Added website_banner: the newsletter alone does not reach anyone in time for an "
                      f"{posture}.")
    if not channels:
        channels = [QUIET_CHANNELS[0]]
        checks.append("No channel survived the checks, so the notice goes in the newsletter.")

    return response.model_copy(update={"posture": posture, "priority": priority, "channels": channels}), checks


def _clamp_channels(channels: list[Channel], posture: Posture) -> tuple[list[Channel], list[str]]:
    """Channels this posture may use, in the order given, without repeats."""
    kept: list[Channel] = []
    dropped: list[str] = []
    for channel in channels:
        floor = CHANNEL_FLOOR.get(channel)
        if floor is not None and posture_rank(posture) < posture_rank(floor):
            dropped.append(channel)
        elif channel not in kept:
            kept.append(channel)
    return kept, dropped


# --- the fallback -----------------------------------------------------------------------------


def fallback_routes(scores: list[TrailScore], trail_name: str,
                    bypass_name: str | None) -> tuple[list[AvoidRoute], list[SafeRoute]]:
    """Three and three from the shortlists, with plain sentences built from the numbers alone.

    Used when the Risk Synthesizer never returns a usable set. The advisory is worse written this
    way, and just as true.
    """
    comparative = relative_only(scores, needed=3, limit=SAFE_POOL)
    instead = f"the {bypass_name}" if bypass_name else "a trail on the safe list below"
    avoid = [
        AvoidRoute(
            trail=score.name,
            reason=(f"The map puts {score.share_high:.0%} of the {score.name} at high or above, peaking at "
                    f"{score.max_probability:.2f}"
                    + (" where it crosses the hazard zone." if score.crosses_zone else ".")),
            instead=f"Send hikers to {instead} instead.",
        )
        for score in avoid_pool(scores)[:3]
    ]
    safe = [
        SafeRoute(
            trail=score.name,
            reason=(f"The {score.name} peaks at {score.max_probability:.2f}, in the {score.level} band, and "
                    f"none of it reaches the hazard zone."),
            caution=("It is the least exposed ground on the mountain today, not safe ground: keep the group "
                     "together and turn around if the weather closes in."
                     if comparative else
                     "Expect mud and run-off underfoot after the rain."),
        )
        for score in safe_pool(scores)[:3]
    ]
    return avoid, safe


def fallback_response(severity: RiskLevel, action: str, needs_review: bool, trail_name: str,
                      miles: str | None) -> RangerResponse:
    """The plainest response the policy allows for this severity: what the code would do alone."""
    low, _ = POSTURE_RANGE[severity]
    posture: Posture = low
    if action == "monitor" and posture_rank(posture) > posture_rank(MONITOR_CEILING):
        posture = MONITOR_CEILING
    if needs_review and posture_rank(posture) > posture_rank(REVIEW_CEILING):
        posture = REVIEW_CEILING
    where = f"{trail_name} {miles}" if miles else trail_name
    quiet = posture_rank(posture) <= posture_rank("watch")
    channels: list[Channel] = (
        ["newsletter", "website_banner"] if quiet
        else ["trailhead_signage", "website_banner", "visitor_center_briefing"]
    )
    actions = (
        [f"Keep {where} on the daily watch list.", "Re-run the analysis after the next rain."]
        if quiet else
        [f"Post the {POSTURE_WORDS[posture].lower()} at the trailheads for {where}.",
         f"Brief the desk so staff can redirect hikers off {where}.",
         "Re-run the analysis in the morning and after any heavy rain."]
    )
    if action == "close":
        actions.insert(0, f"Close {where}.")
    return RangerResponse(
        posture=posture,
        priority=PRIORITY_RANGE[posture][0],
        headline=f"{POSTURE_WORDS[posture]}: {severity} landslide risk on the {where}.",
        channels=channels,
        actions=actions[:5],
        staffing=("No one needs to move today." if quiet
                  else f"Put a ranger at the {trail_name} trailhead through the afternoon."),
        timeline="Act today and look again after the next rain.",
        escalate_if="New cracks, fresh debris, or rain beyond the forecast appear on these miles.",
    )
