"""The router's choice between Gemini Flash and Grok, rule by rule. No network."""

from dataclasses import dataclass

import pytest

from app.agents.router import REST_S, NoProviderError, Router, Signals


@dataclass
class FakeProvider:
    name: str
    model: str
    configured: bool = True

    @property
    def label(self) -> str:
        return {"gemini": "Gemini 3.8 Flash", "grok": "Grok 4.3"}[self.name]


def router(gemini=True, grok=True, env=None, clock=None):
    providers = {"gemini": FakeProvider("gemini", "gemini-3.8-flash", gemini),
                 "grok": FakeProvider("grok", "grok-4.3", grok)}
    kwargs = {"clock": clock} if clock else {}
    return Router(providers, env=env or {}, **kwargs)


@pytest.mark.parametrize(("agent", "signals", "expected"), [
    ("terrain", Signals(zone_peak=0.96), "gemini"),
    ("terrain", Signals(zone_peak=0.72), "gemini"),  # Grok off by default
    ("terrain", Signals(zone_peak=0.46), "gemini"),
    ("weather", Signals(rain_ratio=3.4), "gemini"),
    ("weather", Signals(rain_ratio=0.2), "gemini"),
    ("weather", Signals(rain_ratio=1.1), "gemini"),
    ("trail", Signals(bypass_exists=True, bypass_level="moderate"), "gemini"),
    ("trail", Signals(bypass_exists=True, bypass_level="extreme"), "gemini"),
    ("trail", Signals(bypass_exists=False), "gemini"),
    ("synthesizer", Signals(report_levels=("moderate", "moderate", "moderate")), "gemini"),
    ("synthesizer", Signals(report_levels=("high", "high", "high")), "gemini"),
    ("synthesizer", Signals(report_levels=("low", "moderate", "low")), "gemini"),
    ("writer", Signals(final_level="moderate", needs_review=False), "gemini"),
    ("writer", Signals(final_level="extreme", needs_review=False), "gemini"),
    ("writer", Signals(final_level="moderate", needs_review=True), "gemini"),
])
def test_task_rules_fast_default(agent, signals, expected):
    decision = router().route(agent, signals)
    assert decision.provider == expected
    assert decision.fallback == [p for p in ("gemini", "grok") if p != expected]
    assert decision.reason.startswith(decision.label)
    assert decision.rules[0].rule == "tier"


@pytest.mark.parametrize(("agent", "signals", "expected"), [
    ("terrain", Signals(zone_peak=0.72), "grok"),
    ("weather", Signals(rain_ratio=1.1), "grok"),
    ("synthesizer", Signals(report_levels=("high", "high", "high")), "grok"),
    ("writer", Signals(final_level="extreme", needs_review=False), "grok"),
])
def test_grok_escalations_when_enabled(agent, signals, expected):
    decision = router(env={"LLM_USE_GROK": "1"}).route(agent, signals)
    assert decision.provider == expected


def test_latency_budget_moves_grok_to_gemini():
    decision = router(env={"LLM_USE_GROK": "1"}).route(
        "writer", Signals(final_level="extreme", elapsed_s=15),
    )
    assert decision.provider == "gemini"
    assert any(r.rule == "latency budget" and r.verdict == "gemini" for r in decision.rules)


def test_budget_leaves_gemini_alone():
    decision = router().route("terrain", Signals(zone_peak=0.96, elapsed_s=55))
    assert decision.provider == "gemini"


def test_missing_key_hands_the_call_to_the_other_provider():
    decision = router(gemini=False).route("terrain", Signals(zone_peak=0.96))
    assert decision.provider == "grok"
    assert decision.rules[-1].rule == "availability"
    assert "no API key" in decision.reason
    assert decision.fallback == []


def test_no_provider_raises():
    with pytest.raises(NoProviderError, match="GEMINI_API_KEY or XAI_API_KEY"):
        router(gemini=False, grok=False).route("terrain", Signals())


def test_forced_provider():
    decision = router(env={"LLM_ROUTER": "grok"}).route("terrain", Signals(zone_peak=0.96))
    assert decision.provider == "grok"
    assert decision.rules[0].rule == "forced"


def test_two_failures_rest_a_provider_then_it_returns():
    now = [1000.0]
    r = router(clock=lambda: now[0])
    r.record_failure("gemini")
    assert r.route("terrain", Signals(zone_peak=0.96)).provider == "gemini"
    r.record_failure("gemini")
    decision = r.route("terrain", Signals(zone_peak=0.96))
    assert decision.provider == "grok" and "resting" in decision.reason
    now[0] += REST_S + 1
    assert r.route("terrain", Signals(zone_peak=0.96)).provider == "gemini"


def test_success_clears_failures():
    r = router(env={"LLM_USE_GROK": "1"})
    r.record_failure("grok")
    r.record_success("grok")
    r.record_failure("grok")
    assert r.route("synthesizer", Signals(report_levels=("high", "high", "high"))).provider == "grok"


def test_all_resting_still_routes():
    r = router()
    for name in ("gemini", "grok"):
        r.record_failure(name)
        r.record_failure(name)
    decision = r.route("terrain", Signals(zone_peak=0.96))
    assert decision.provider == "gemini"
    assert "tries again" in decision.rules[-1].detail
