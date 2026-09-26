"""The router that picks Gemini Flash or Grok for each agent call.

It runs in code before every model call, so it adds no latency and every choice can be read in
the reasoning panel. It checks, in order:

1. Tier. The five analysts are fast-tier and start on Gemini Flash, which answers structured
   extraction in seconds and lets all five run at once. Strong-tier agents (Synthesizer, Alert
   Writer) start on Grok, which reasons more deliberately over conflicting reports.
2. The task. Ambiguity escalates a fast task to Grok: a zone peak within 0.05 of a bin edge,
   rain within a third of the one-week threshold, a trail with no safe bypass, an empty landslide
   catalog, or a mountain with too few clear trails to recommend. A clear, low-stakes call brings
   a strong task down to Gemini: analysts that agree at low or moderate, or a routine monitor
   notice.
3. Latency budget. Past 70% of the run's budget (RUN_BUDGET_S, default 20 s for demos), a Grok pick moves to Gemini.
4. Availability. A provider needs its API key, and one that failed twice in two minutes rests
   for a minute. When the pick is out, the other provider takes the call. When every provider
   with a key is resting, the router tries them anyway rather than fail the run.

LLM_ROUTER=gemini or LLM_ROUTER=grok forces one provider for every call, for testing.
LLM_USE_GROK=1 turns Grok back on for strong-tier agents and ambiguity escalations (grok-4.3, effort none by default).
The provider the router did not pick is the fallback when the pick fails.
"""

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from app.risk import BIN_EDGES, RiskLevel, level_index, level_spread

from .providers import Provider
from .schemas import (
    AGENT_LABELS,
    AgentName,
    ProviderName,
    RouteDecision,
    RouteRule,
    Tier,
)

TIERS: dict[AgentName, Tier] = {
    "terrain": "fast",
    "weather": "fast",
    "trail": "fast",
    "history": "fast",
    "routes": "fast",
    "synthesizer": "strong",
    "writer": "strong",
}
PROVIDER_ORDER: tuple[ProviderName, ...] = ("gemini", "grok")
TIER_FAST: ProviderName = "gemini"
TIER_STRONG_GROK: ProviderName = "grok"
TIER_STRONG_FAST: ProviderName = "gemini"

RUN_BUDGET_S = 20  # demo target: five analysts in parallel, then synthesizer, then writer
BUDGET_SHARE = 0.7  # past this share of the budget, speed wins
EDGE_MARGIN = 0.05  # a zone peak this close to a bin edge is a close call
RAIN_BAND = (0.67, 1.5)  # rain within a third of the one-week threshold is a close call
FAILURES_TO_REST = 2
FAILURE_WINDOW_S = 120
REST_S = 60


class NoProviderError(RuntimeError):
    """Neither provider can take a call."""


@dataclass
class Signals:
    """What the router knows about one agent call. Each agent fills the fields that matter to it."""

    elapsed_s: float = 0.0
    zone_peak: float | None = None  # terrain
    rain_ratio: float | None = None  # weather: the wetter of past week and next week, over the threshold
    bypass_exists: bool | None = None  # trail
    bypass_level: RiskLevel | None = None
    analog_count: int | None = None  # history: catalog events near the zone
    clear_routes: int | None = None  # routes: trails clearing the safe ceiling
    report_levels: tuple[RiskLevel, ...] = ()  # synthesizer: every analyst's severity
    final_level: RiskLevel | None = None  # writer
    needs_review: bool | None = None


@dataclass
class _Health:
    failures: list[float] = field(default_factory=list)


def _env_flag(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


class Router:
    def __init__(self, providers: Mapping[ProviderName, Provider], env: Mapping[str, str] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        env = os.environ if env is None else env
        self.providers = dict(providers)
        self.forced = (env.get("LLM_ROUTER", "").strip() or "auto").lower()
        self.use_grok = _env_flag(env, "LLM_USE_GROK", default=False)
        self.clock = clock
        self._health: dict[ProviderName, _Health] = {name: _Health() for name in self.providers}

    def _tier_default(self, tier: Tier) -> ProviderName:
        if tier == "fast":
            return TIER_FAST
        return TIER_STRONG_GROK if self.use_grok else TIER_STRONG_FAST

    # --- health ---------------------------------------------------------------------------

    def record_failure(self, name: ProviderName) -> None:
        now = self.clock()
        health = self._health[name]
        health.failures = [t for t in health.failures if now - t <= FAILURE_WINDOW_S] + [now]

    def record_success(self, name: ProviderName) -> None:
        self._health[name].failures.clear()

    def resting(self, name: ProviderName) -> bool:
        now = self.clock()
        recent = [t for t in self._health[name].failures if now - t <= FAILURE_WINDOW_S]
        return len(recent) >= FAILURES_TO_REST and now - recent[-1] <= REST_S

    def available(self) -> dict[ProviderName, bool]:
        return {name: provider.configured and not self.resting(name) for name, provider in self.providers.items()}

    # --- routing --------------------------------------------------------------------------

    def route(self, agent: AgentName, signals: Signals) -> RouteDecision:
        available = self.available()
        recovering = False
        if not any(available.values()):
            configured = {name: provider.configured for name, provider in self.providers.items()}
            if not any(configured.values()):
                raise NoProviderError("No LLM provider has an API key. Set GEMINI_API_KEY or XAI_API_KEY in .env.")
            # Resting steers calls away from a failing provider while another can take them. With
            # every configured provider resting, trying again beats failing the run outright.
            available, recovering = configured, True

        tier = TIERS[agent]
        rules: list[RouteRule] = []
        deciding: RouteRule
        explaining: RouteRule | None = None  # the most specific rule behind the choice
        if self.forced in self.providers:
            choice: ProviderName = self.forced  # type: ignore[assignment]
            deciding = RouteRule(rule="forced", verdict=choice,
                                 detail=f"LLM_ROUTER={self.forced} sends every call to {self._label(choice)}.")
            rules.append(deciding)
        else:
            choice = self._tier_default(tier)
            deciding = RouteRule(rule="tier", verdict=choice, detail=_tier_detail(tier, self.use_grok))
            rules.append(deciding)
            task_rule = _TASK_RULES[agent](signals, choice, self.use_grok)
            rules.append(task_rule)
            explaining = task_rule
            if task_rule.verdict and task_rule.verdict != choice:
                choice, deciding = task_rule.verdict, task_rule
            budget_rule = self._budget(signals, choice, available)
            rules.append(budget_rule)
            if budget_rule.verdict and budget_rule.verdict != choice:
                choice, deciding, explaining = budget_rule.verdict, budget_rule, budget_rule

        if not available[choice]:
            other = next(name for name in PROVIDER_ORDER if available.get(name))
            why = "has no API key" if not self.providers[choice].configured else "failed twice in two minutes and is resting"
            deciding = RouteRule(rule="availability", verdict=other,
                                 detail=f"{self._label(choice)} {why}, so {self._label(other)} takes the call.")
            rules.append(deciding)
            explaining = deciding
            choice = other
        elif recovering:
            rules.append(RouteRule(rule="availability", verdict=None,
                                   detail="Every provider failed in the last two minutes, so the router tries again "
                                          "instead of giving up."))
        else:
            rules.append(RouteRule(rule="availability", verdict=None, detail=self._availability_note(available)))

        provider = self.providers[choice]
        return RouteDecision(
            provider=choice,
            model=provider.model,
            label=provider.label,
            tier=tier,
            reason=f"{provider.label} for the {AGENT_LABELS[agent]}. {(explaining or deciding).detail}",
            rules=rules,
            fallback=[name for name in PROVIDER_ORDER if name != choice and available.get(name)],
            available={name: bool(ok) for name, ok in available.items()},
        )

    def _budget(self, signals: Signals, choice: ProviderName, available: dict[ProviderName, bool]) -> RouteRule:
        used = signals.elapsed_s
        if choice == "grok" and used > BUDGET_SHARE * RUN_BUDGET_S and available.get("gemini"):
            return RouteRule(rule="latency budget", verdict="gemini",
                             detail=f"The run has used {used:.0f} s of its {RUN_BUDGET_S} s budget, so the faster "
                                    "model keeps the alert on time.")
        return RouteRule(rule="latency budget", verdict=None,
                         detail=f"{used:.0f} s of the {RUN_BUDGET_S} s budget used, so no change.")

    def _availability_note(self, available: dict[ProviderName, bool]) -> str:
        down = [self._label(n) for n, ok in available.items() if not ok]
        if not down:
            return "Both providers are ready, so the other one is the fallback."
        return f"{' and '.join(down)} cannot take calls right now, so there is no fallback."

    def _label(self, name: ProviderName) -> str:
        return self.providers[name].label


def _tier_detail(tier: Tier, use_grok: bool) -> str:
    if tier == "fast":
        return ("A fast-tier task: Gemini Flash turns precomputed facts into structured JSON in seconds, so "
                "all five analysts can run at once.")
    if use_grok:
        return "A strong-tier task: Grok weighs conflicting reports more deliberately."
    return ("A strong-tier task: Gemini Flash keeps synthesizer and writer inside the ~20 s demo budget "
            "(set LLM_USE_GROK=1 for Grok on these steps).")


def _grok_or_none(use_grok: bool, detail: str) -> RouteRule:
    if not use_grok:
        return RouteRule(rule="latency", verdict=None,
                         detail=f"{detail} Grok is off (LLM_USE_GROK), so Gemini keeps the run fast.")
    return RouteRule(rule="ambiguity", verdict="grok", detail=detail)


def _terrain(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    if signals.zone_peak is None:
        return RouteRule(rule="ambiguity", verdict=None, detail="There is no hazard zone, so nothing is borderline.")
    edge = min(BIN_EDGES, key=lambda e: abs(signals.zone_peak - e))
    gap = abs(signals.zone_peak - edge)
    if gap <= EDGE_MARGIN:
        return _grok_or_none(use_grok,
                             f"The zone peaks at {signals.zone_peak:.2f}, {gap:.2f} from the {edge} bin edge, "
                             "so its level is a close call for the stronger model.")
    return RouteRule(rule="ambiguity", verdict=None,
                     detail=f"The zone peaks at {signals.zone_peak:.2f}, {gap:.2f} from the nearest bin edge, "
                            "so its level is clear.")


def _weather(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    ratio = signals.rain_ratio
    if ratio is None:
        return RouteRule(rule="ambiguity", verdict=None, detail="No rain ratio to judge.")
    low, high = RAIN_BAND
    if low <= ratio <= high:
        return _grok_or_none(use_grok,
                             f"Rain is {ratio:.1f}x the one-week threshold, near the line, so it is a judgment call.")
    side = "above" if ratio > high else "below"
    return RouteRule(rule="ambiguity", verdict=None,
                     detail=f"Rain is {ratio:.1f}x the one-week threshold, well {side} the line, so the read is clear.")


def _trail(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    if signals.bypass_exists is False:
        return _grok_or_none(use_grok,
                             "No trail runs around the flagged miles, so the turn-back advice needs care.")
    if signals.bypass_level is not None and level_index(signals.bypass_level) >= level_index("high"):
        return _grok_or_none(use_grok,
                             f"The bypass crosses {signals.bypass_level} ground itself, so weighing two risky "
                             "routes goes to the stronger model.")
    return RouteRule(rule="stakes", verdict=None, detail="The bypass stays on safer ground, so the explanation is routine.")


def _history(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    count = signals.analog_count
    if count is None:
        return RouteRule(rule="ambiguity", verdict=None, detail="No catalog to judge.")
    if count == 0:
        return _grok_or_none(use_grok,
                             "The catalog holds no event near the zone, and reading an absence without "
                             "calling it safety is a judgment call.")
    return RouteRule(rule="ambiguity", verdict=None,
                     detail=f"{count} catalog event{'s' if count != 1 else ''} sit near the zone, so the record "
                            "speaks for itself.")


def _routes(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    clear = signals.clear_routes
    if clear is None:
        return RouteRule(rule="stakes", verdict=None, detail="No route catalog to judge.")
    if clear < 3:
        return _grok_or_none(use_grok,
                             f"Only {clear} trail{'s' if clear != 1 else ''} on the mountain clear the safe "
                             "ceiling, so recommending the least exposed ground needs the stronger model.")
    return RouteRule(rule="stakes", verdict=None,
                     detail=f"{clear} trails clear the safe ceiling, so there is real choice for the safe list.")


def _synthesizer(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    levels = signals.report_levels
    if not levels:
        return RouteRule(rule="stakes", verdict=None, detail="No reports to compare.")
    spread = level_spread(levels)
    top = max(levels, key=level_index)
    if spread == 0 and level_index(top) <= level_index("moderate"):
        return RouteRule(rule="stakes", verdict="gemini",
                         detail=f"All {len(levels)} analysts say {top}, a clear, low-stakes call the fast model "
                                "can make.")
    agreement = "agree" if spread == 0 else f"span {spread} level{'s' if spread > 1 else ''}"
    return RouteRule(rule="stakes", verdict=None,
                     detail=f"The {len(levels)} reports {agreement} and the top rating is {top}, so the stronger "
                            "model decides.")


def _writer(signals: Signals, choice: ProviderName, use_grok: bool) -> RouteRule:
    level = signals.final_level
    if signals.needs_review:
        return RouteRule(rule="stakes", verdict=None,
                         detail="The reports disagree, so the advisory's wording needs the stronger model.")
    if level is not None and level_index(level) <= level_index("moderate"):
        return RouteRule(rule="stakes", verdict="gemini",
                         detail=f"A {level} monitor notice is routine copy for the fast model.")
    return RouteRule(rule="stakes", verdict=None,
                     detail=f"The final level is {level}, so public-safety copy stays on the stronger model.")


_TASK_RULES: dict[AgentName, Callable[[Signals, ProviderName, bool], RouteRule]] = {
    "terrain": _terrain,
    "weather": _weather,
    "trail": _trail,
    "history": _history,
    "routes": _routes,
    "synthesizer": _synthesizer,
    "writer": _writer,
}
