"""The shared risk vocabulary: levels, probability bins, and level colors.

Values come from the Shared facts in context/implementation-steps.md and the Design Language
in context/TerraSense.md. Keep this module free of API, database, and Pydantic imports:
the tiler (app/ml/tiles.py) and the offline scripts in ml/scripts/ import it too.
"""

from collections.abc import Iterable
from typing import Literal

RiskLevel = Literal["low", "moderate", "high", "extreme"]
RISK_LEVELS: tuple[RiskLevel, ...] = ("low", "moderate", "high", "extreme")

# Probability bins: low < 0.2, moderate 0.2-0.45, high 0.45-0.7, extreme > 0.7.
# These are the upper edges of low, moderate, and high.
BIN_EDGES = (0.2, 0.45, 0.7)
# The lower edge of "high": the segments a bypass avoids and the cells a hazard zone holds.
HIGH_THRESHOLD = BIN_EDGES[1]

# Model ceiling. Raw scores above the knee are squeezed linearly into [knee, ceiling], so a
# model that says 0.93 or 1.0 reads 0.78 or 0.80: still "extreme", still ranked, never certain.
# Every bin edge sits at or below the knee, so levels and thresholds do not move.
PROBABILITY_KNEE = 0.70
PROBABILITY_CEILING = 0.80

# Level colors from Design Language. The backend needs them for the map tiles. The frontend
# keeps its own copies in globals.css and lib/theme.ts.
RISK_HEX: dict[RiskLevel, str] = {
    "low": "#22C55E",
    "moderate": "#F59E0B",
    "high": "#F97316",
    "extreme": "#EF4444",
}


def risk_level(probability: float) -> RiskLevel:
    """The shared level for a 0-1 probability."""
    for edge, level in zip(BIN_EDGES, RISK_LEVELS, strict=False):
        if probability < edge:
            return level
    return "extreme"


def cap_probability(probability: float) -> float:
    """A 0-1 model score with everything above PROBABILITY_KNEE compressed under PROBABILITY_CEILING."""
    value = min(1.0, max(0.0, float(probability)))
    if value <= PROBABILITY_KNEE:
        return value
    return PROBABILITY_KNEE + (PROBABILITY_CEILING - PROBABILITY_KNEE) * (value - PROBABILITY_KNEE) / (1.0 - PROBABILITY_KNEE)


def level_index(level: RiskLevel) -> int:
    """0 for low through 3 for extreme."""
    return RISK_LEVELS.index(level)


def level_spread(levels: Iterable[RiskLevel]) -> int:
    """How many levels apart the highest and lowest ratings are. 0 when they agree."""
    indexes = [level_index(level) for level in levels]
    return max(indexes) - min(indexes) if indexes else 0


def hex_rgb(hex_color: str) -> tuple[int, int, int]:
    """'#F97316' to (249, 115, 22)."""
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
