"""Past-run context for the agents, and the seam a context manager plugs into (step 34).

Until now every run started cold: the agents saw today's map and today's weather and nothing
else. The database has been accumulating the rest — `previous_runs` (step 33) holds every run
this system has ever made, and `hazards` holds every zone it ever saved. This module turns that
into facts the agents can read, so a run can say "this slope was rated high twice last week and
nothing came of it" instead of pretending today is the first day.

Three things live here.

**Blocks.** One `ContextBlock` is one coherent piece of background: the mountain's past runs in
this domain, its saved hazards, or what the *other* domain concluded recently. Each carries a
priority and a rough token cost.

**Sources.** A `ContextSource` fetches one block. Adding background means adding a source to
DEFAULT_SOURCES, not editing a pipeline.

**The manager seam.** `ContextManager` is a one-method protocol: given every block and an
optional token budget, return the blocks to actually show this agent, in order. The only
implementation today is `PriorityManager`, which sorts by priority and cuts at the budget — no
model, no network, no judgment. That is deliberate. When an AI context-management layer is
built, it implements this same protocol and `build_bundle(manager=...)` takes it; nothing in
the pipelines changes. This module does not contain, start, or call such a layer.

Every read here is fail-soft. Background is a nice-to-have: a database hiccup must degrade an
agent's context, never fail its run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.db import get_pool
from app.domains import DEFAULT_DOMAIN, HazardDomain

logger = logging.getLogger(__name__)

# How many past items each source pulls. Small on purpose: this is background, and a long tail
# of old runs pushes today's facts out of the model's attention.
PAST_RUN_LIMIT = 8
PAST_HAZARD_LIMIT = 5
CROSS_DOMAIN_LIMIT = 3

# Rough token cost of a rendered block: JSON characters over four. Good enough to keep a budget
# honest without importing a tokenizer.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ContextBlock:
    """One coherent piece of background an agent may be shown."""

    source: str          # the source's name, for tracing
    title: str           # the heading the agent sees above the JSON
    facts: dict[str, Any]
    priority: int        # lower is more important; the default manager sorts on it

    @property
    def approx_tokens(self) -> int:
        return len(json.dumps(self.facts, default=str)) // CHARS_PER_TOKEN

    @property
    def is_empty(self) -> bool:
        """True when the block has nothing to say, so it can be dropped rather than shown blank."""
        return not any(self.facts.get(key) for key in self.facts if key != "note")


@runtime_checkable
class ContextSource(Protocol):
    """Fetches one block of background for a run."""

    name: str
    priority: int

    def fetch(self, ctx) -> ContextBlock | None: ...


class ContextManager(Protocol):
    """Chooses which blocks an agent actually sees.

    THE SEAM. A future AI context-management layer implements exactly this and is passed to
    `build_bundle(manager=...)`; no pipeline changes. `select` must be cheap and must never
    raise: it runs inside a live run.
    """

    def select(self, blocks: list[ContextBlock], *, agent: str,
               budget_tokens: int | None = None) -> list[ContextBlock]: ...


class PriorityManager:
    """The default manager: sort by priority, drop empties, cut at the budget. No model."""

    def select(self, blocks: list[ContextBlock], *, agent: str,
               budget_tokens: int | None = None) -> list[ContextBlock]:
        ordered = sorted((b for b in blocks if not b.is_empty), key=lambda b: (b.priority, b.source))
        if budget_tokens is None:
            return ordered
        kept, spent = [], 0
        for block in ordered:
            if spent + block.approx_tokens > budget_tokens:
                continue  # skip this one, a smaller later block may still fit
            kept.append(block)
            spent += block.approx_tokens
        return kept


@dataclass
class ContextBundle:
    """The background gathered for one run, and the manager that decides what to show."""

    blocks: list[ContextBlock] = field(default_factory=list)
    manager: ContextManager = field(default_factory=PriorityManager)

    def for_agent(self, agent: str, budget_tokens: int | None = None) -> dict[str, dict]:
        """The context mapping to merge into an agent's `context=` argument.

        Keys are the block titles, which is the shape Pipeline._message renders.
        """
        try:
            chosen = self.manager.select(self.blocks, agent=agent, budget_tokens=budget_tokens)
        except Exception:  # a manager must never take a run down with it
            logger.exception("context manager failed for %s; showing every block", agent)
            chosen = [b for b in self.blocks if not b.is_empty]
        return {block.title: block.facts for block in chosen}

    @property
    def sources(self) -> list[str]:
        return [block.source for block in self.blocks]


# --- The sources -----------------------------------------------------------------------------


def _rows(sql: str, params: list) -> list[dict]:
    """A read that never raises. Background is optional; the run is not."""
    try:
        with get_pool().connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception:
        logger.exception("past-data context query failed; the agents run without this block")
        return []


@dataclass(frozen=True)
class PastRunsSource:
    """What this system already concluded about this mountain, in this domain.

    Straight off `previous_runs` (step 33). The agents are told plainly that these are the
    system's own past outputs, not observations: nothing here confirms that an event happened.
    """

    name: str = "past_runs"
    priority: int = 1
    limit: int = PAST_RUN_LIMIT

    def fetch(self, ctx) -> ContextBlock | None:
        rows = _rows(
            """
            SELECT started_at, status, severity, confidence, hazard_class, hazard_type,
                   recommended_action, posture, needs_review, headline, summary,
                   model_method, model_max_probability, snow_driven
            FROM previous_runs
            WHERE mountain_slug = %s AND domain = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            [ctx.slug, ctx.domain, self.limit],
        )
        runs = [
            {
                "when": r["started_at"].isoformat() if r["started_at"] else None,
                "status": r["status"],
                "severity": r["severity"],
                "confidence": r["confidence"],
                "hazard_type": r["hazard_type"],
                "action": r["recommended_action"],
                "posture": r["posture"],
                "was_advisory": r["needs_review"],
                "headline": r["headline"],
                "model_method": r["model_method"],
                "model_max_probability": r["model_max_probability"],
            }
            for r in rows
        ]
        finished = [r for r in runs if r["status"] == "done" and r["severity"]]
        return ContextBlock(
            source=self.name,
            title=f"Past TerraSense {ctx.domain} runs on this mountain",
            priority=self.priority,
            facts={
                "what_this_is": (
                    "This system's own previous conclusions for this mountain, newest first. "
                    "They are model and agent outputs, NOT observations: none of them confirms "
                    "that a slide or an avalanche actually happened. Use them for consistency "
                    "(has the rating swung around?) and never as evidence that today is safe."
                ),
                "runs_shown": len(runs),
                "finished_runs": len(finished),
                "levels_seen": sorted({r["severity"] for r in finished}) if finished else [],
                "last_severity": finished[0]["severity"] if finished else None,
                "last_run_at": finished[0]["when"] if finished else None,
                "runs": runs,
                "note": None if runs else "No previous run has been recorded for this mountain and domain.",
            },
        )


@dataclass(frozen=True)
class PastHazardsSource:
    """Hazard zones this system saved here before, with the miles they covered."""

    name: str = "past_hazards"
    priority: int = 2
    limit: int = PAST_HAZARD_LIMIT

    def fetch(self, ctx) -> ContextBlock | None:
        rows = _rows(
            """
            SELECT h.created_at, h.type, h.severity, h.probability, h.confidence, h.drivers,
                   h.what, h.start_mile, h.end_mile, h.needs_review, t.name AS trail
            FROM hazards h
            JOIN mountains m ON m.id = h.mountain_id
            LEFT JOIN trails t ON t.id = h.trail_id
            WHERE m.slug = %s AND h.domain = %s
            ORDER BY h.created_at DESC
            LIMIT %s
            """,
            [ctx.slug, ctx.domain, self.limit],
        )
        hazards = [
            {
                "when": r["created_at"].isoformat() if r["created_at"] else None,
                "type": r["type"],
                "severity": r["severity"],
                "max_probability": r["probability"],
                "drivers": r["drivers"],
                "trail": r["trail"],
                "miles": None if r["start_mile"] is None else [r["start_mile"], r["end_mile"]],
                "what": r["what"],
            }
            for r in rows
        ]
        return ContextBlock(
            source=self.name,
            title=f"Hazard zones saved here before ({ctx.domain})",
            priority=self.priority,
            facts={
                "what_this_is": (
                    "Zones this system saved on earlier runs, newest first. Again: saved model "
                    "output, not a record that anything released. Useful for whether the same "
                    "miles keep coming up."
                ),
                "hazards": hazards,
                "recurring_miles": _recurring_miles(hazards),
                "note": None if hazards else "No hazard zone has been saved for this mountain and domain.",
            },
        )


@dataclass(frozen=True)
class CrossDomainSource:
    """What the *other* hazard domain concluded here recently.

    A snowpack run benefits from knowing a wet-slope landslide warning went out yesterday, and
    a landslide run benefits from knowing the mountain was under an avalanche warning. Kept
    short and clearly labeled as the other domain, so no agent folds it into its own call.
    """

    name: str = "other_domain"
    priority: int = 3
    limit: int = CROSS_DOMAIN_LIMIT

    def fetch(self, ctx) -> ContextBlock | None:
        other: HazardDomain = "landslide" if ctx.domain == "avalanche" else "avalanche"
        rows = _rows(
            """
            SELECT started_at, severity, hazard_type, recommended_action, posture, headline
            FROM previous_runs
            WHERE mountain_slug = %s AND domain = %s AND status = 'done'
            ORDER BY started_at DESC
            LIMIT %s
            """,
            [ctx.slug, other, self.limit],
        )
        runs = [
            {
                "when": r["started_at"].isoformat() if r["started_at"] else None,
                "severity": r["severity"],
                "hazard_type": r["hazard_type"],
                "action": r["recommended_action"],
                "posture": r["posture"],
                "headline": r["headline"],
            }
            for r in rows
        ]
        return ContextBlock(
            source=self.name,
            title=f"Recent {other} runs on this mountain (the other hazard domain)",
            priority=self.priority,
            facts={
                "what_this_is": (
                    f"These are {other} conclusions, not {ctx.domain} ones. They tell you what "
                    f"else the mountain is dealing with. Do NOT let them set your own severity: "
                    f"rate the {ctx.domain} hazard on your own facts."
                ),
                "domain": other,
                "runs": runs,
                "note": None if runs else f"No finished {other} run has been recorded here.",
            },
        )


DEFAULT_SOURCES: tuple[ContextSource, ...] = (
    PastRunsSource(),
    PastHazardsSource(),
    CrossDomainSource(),
)


def _recurring_miles(hazards: list[dict]) -> list[float]:
    """Mile markers that appear in more than one saved hazard, rounded to the nearest half mile."""
    counts: dict[float, int] = {}
    for hazard in hazards:
        miles = hazard.get("miles")
        if not miles or miles[0] is None or miles[1] is None:
            continue
        step = round(miles[0] * 2) / 2
        while step <= miles[1]:
            counts[step] = counts.get(step, 0) + 1
            step += 0.5
    return sorted(mile for mile, n in counts.items() if n > 1)


def build_bundle(ctx, sources: tuple[ContextSource, ...] = DEFAULT_SOURCES,
                 manager: ContextManager | None = None) -> ContextBundle:
    """Gather every source's block for one run.

    Pass `manager` to swap in a different selection strategy; the default is priority order.
    A source that raises is skipped with a log line, never propagated into the run.
    """
    blocks: list[ContextBlock] = []
    for source in sources:
        try:
            block = source.fetch(ctx)
        except Exception:
            logger.exception("context source %s failed; skipping it", getattr(source, "name", source))
            continue
        if block is not None:
            blocks.append(block)
    return ContextBundle(blocks=blocks, manager=manager or PriorityManager())


def empty_bundle() -> ContextBundle:
    """A bundle with nothing in it, for tests and for runs that deliberately start cold."""
    return ContextBundle(blocks=[], manager=PriorityManager())


__all__ = [
    "DEFAULT_DOMAIN",
    "ContextBlock",
    "ContextBundle",
    "ContextManager",
    "ContextSource",
    "CrossDomainSource",
    "PastHazardsSource",
    "PastRunsSource",
    "PriorityManager",
    "build_bundle",
    "empty_bundle",
]
