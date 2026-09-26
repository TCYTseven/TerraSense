"""The hazard domains TerraSense runs: landslide and avalanche (step 34).

One domain is one end-to-end hazard story: its own terrain model and artifacts, its own
driver vocabulary, its own agent framing, and its own analyze route. Everything downstream of
scoring is shared, because both domains hand back the same `ProbabilityMap` on the same 30 m
grid: the tiler, the hazard zone, the trail segment scoring, and the bypass never learn which
domain they are serving.

Keep this module free of API, database, Pydantic, and numpy imports, like app/risk.py: the
offline scripts, the tiler, the ML seams, and the agents all import it.

Adding a third domain means adding a DomainSpec here and a scorer that returns a
ProbabilityMap. It does not mean touching the pipeline's plumbing.
"""

from dataclasses import dataclass
from typing import Literal

HazardDomain = Literal["landslide", "avalanche"]
HAZARD_DOMAINS: tuple[HazardDomain, ...] = ("landslide", "avalanche")

# The domain the original routes and the existing frontend mean when they say nothing.
# POST /mountains/{slug}/analyze is this domain, so nothing built before step 34 changes.
DEFAULT_DOMAIN: HazardDomain = "landslide"

# Every hazard type either domain may produce. The `hazards.type` CHECK and the HazardType
# Literal in app/models.py are generated from this, so the three never drift apart.
LANDSLIDE_TYPES: tuple[str, ...] = ("landslide", "debris_flow")
AVALANCHE_TYPES: tuple[str, ...] = ("slab_avalanche", "loose_snow_avalanche", "wet_snow_avalanche")
HAZARD_TYPES: tuple[str, ...] = LANDSLIDE_TYPES + AVALANCHE_TYPES

# Plain words for a hazard type, for the sentences code writes without a model.
HAZARD_WORDS: dict[str, str] = {
    "landslide": "Landslide",
    "debris_flow": "Debris flow",
    "slab_avalanche": "Slab avalanche",
    "loose_snow_avalanche": "Loose-snow avalanche",
    "wet_snow_avalanche": "Wet-snow avalanche",
}

# --- Drivers -----------------------------------------------------------------------------
#
# The reasons an agent may cite for a hazard. Each domain has its own list: a landslide is
# driven by where water collects and where ground is bare, an avalanche by where snow loads
# and what is under it. `slope_angle` is the only one both share, because steep ground is the
# precondition for each.

LANDSLIDE_DRIVERS: tuple[str, ...] = (
    "slope_angle",
    "drainage_proximity",
    "sparse_vegetation",
    "soil_wetness",
    "concave_hollow",
    "past_landslides",
    "recent_rain",
    "forecast_rain",
)

AVALANCHE_DRIVERS: tuple[str, ...] = (
    "slope_angle",          # the 30-45 deg start-zone band
    "lee_loading",          # wind carries snow onto the sheltered side
    "convex_rollover",      # slabs fracture where the slope rolls over
    "open_slope",           # no trees to anchor the snowpack
    "above_treeline",       # start zones sit high
    "new_snow_load",        # fresh snow in the forecast
    "wind_slab",            # wind stiffens new snow into a slab
    "warming_instability",  # a rising freezing level weakens bonds
    "rain_on_snow",         # rain loads and lubricates the pack
    "past_avalanches",      # the record shows this path runs
)

DRIVERS: dict[HazardDomain, tuple[str, ...]] = {
    "landslide": LANDSLIDE_DRIVERS,
    "avalanche": AVALANCHE_DRIVERS,
}
ALL_DRIVERS: tuple[str, ...] = tuple(dict.fromkeys(LANDSLIDE_DRIVERS + AVALANCHE_DRIVERS))


@dataclass(frozen=True)
class DomainSpec:
    """Everything that differs between one hazard domain and another."""

    domain: HazardDomain
    label: str                  # "Landslide", for a heading
    noun: str                   # "landslide", mid-sentence
    hazard_types: tuple[str, ...]
    default_type: str
    drivers: tuple[str, ...]

    # ML artifacts, following the layout in ml/artifacts/ and packs/<slug>/. Both domains use
    # the same shapes: a baked terrain GeoTIFF and a LightGBM text booster beside it.
    susceptibility_file: str
    probability_file: str
    booster_file: str
    metrics_file: str

    # The XYZ tile layer this domain's probability map renders to, under backend/tiles/.
    tile_layer: str

    # What the run's terrain analyst is called, and the hazard map's plain name. Used in the
    # prompts and in the agent panel's labels.
    analyst_label: str
    map_name: str

    @property
    def is_default(self) -> bool:
        return self.domain == DEFAULT_DOMAIN


LANDSLIDE = DomainSpec(
    domain="landslide",
    label="Landslide",
    noun="landslide",
    hazard_types=LANDSLIDE_TYPES,
    default_type="landslide",
    drivers=LANDSLIDE_DRIVERS,
    # Rainier's legacy step 10-19 names, kept exactly: renaming them would orphan every
    # artifact already on disk and in the packs.
    susceptibility_file="susceptibility.tif",
    probability_file="probability.tif",
    booster_file="susceptibility_lgbm.txt",
    metrics_file="metrics.json",
    tile_layer="probability",
    analyst_label="Terrain Analyst",
    map_name="72-hour landslide map",
)

AVALANCHE = DomainSpec(
    domain="avalanche",
    label="Avalanche",
    noun="avalanche",
    hazard_types=AVALANCHE_TYPES,
    default_type="slab_avalanche",
    drivers=AVALANCHE_DRIVERS,
    susceptibility_file="avalanche_susceptibility.tif",
    probability_file="avalanche_probability.tif",
    booster_file="avalanche_lgbm.txt",
    metrics_file="avalanche_metrics.json",
    tile_layer="avalanche_probability",
    analyst_label="Snowpack Analyst",
    map_name="72-hour avalanche map",
)

SPECS: dict[HazardDomain, DomainSpec] = {"landslide": LANDSLIDE, "avalanche": AVALANCHE}


def spec(domain: HazardDomain | str | None) -> DomainSpec:
    """The spec for a domain. None means the default, so old callers keep working."""
    if domain is None:
        return SPECS[DEFAULT_DOMAIN]
    try:
        return SPECS[domain]  # type: ignore[index]
    except KeyError:
        raise ValueError(
            f"{domain!r} is not a hazard domain. Known: {', '.join(HAZARD_DOMAINS)}"
        ) from None


def domain_of(hazard_type: str | None) -> HazardDomain | None:
    """Which domain a hazard type belongs to, or None when it belongs to neither."""
    for name, value in SPECS.items():
        if hazard_type in value.hazard_types:
            return name
    return None
