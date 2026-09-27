"""The science behind the illustrative runout: how far it spreads, and how fast (step 27).

Every formula and default here comes from context/docs/LANDSLIDE_SIMULATION.md, with the
section named beside it. Two tiers, as that document recommends:

- Tier A, extent (sections 4.1 to 4.4). Holmgren weights times a persistence term decide how
  each cell's share of the flow splits among its lower neighbors. A Flow-Py energy line,
  carried cell by cell, decides where the flow stops: Z_delta is the kinetic-energy head,
  Z_delta = Z_gamma - Z_alpha, capped at V_max^2 / 2g, and a cell is reached only while it
  stays positive.
- Tier B, speed (sections 4.3 and 5). A debris flow moves at the simplified friction-limited
  model's speed (Flow-R), v = sqrt(2 g Z_delta), capped at V_max. A snow avalanche moves
  like a Voellmy sled, integrated exactly over each cell step with the Perla-Cheng-McClung
  closed form (the two are the same equation for a constant slope, with M/D = xi h / g).

Places pick their process by kind: a mountain's runout is a snow avalanche, the pale blue
flow the map draws there; a hill's is a debris flow, drawn as dirt. Two project rules sit on
top of the published models, and each is named where it applies: the flow only ever moves
to a lower cell, and the footprint is an area on the slope, not a line.

Every output is illustrative susceptibility from simplified empirical models (section 12):
not a hazard map, not a forecast of timing, and not an avalanche bulletin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

G = 9.81  # m s^-2

# Persistence weights by turn angle from the incoming flow direction, at 0, 45, 90, 135 and
# 180 degrees (section 4.2, Horton et al. 2013 after Gamma 2000).
PERSISTENCE_PROPORTIONAL = (1.0, 0.8, 0.4, 0.0, 0.0)
PERSISTENCE_COSINE = (1.0, 0.707, 0.0, 0.0, 0.0)

# The alpha-beta regression (section 3.2, Bakkehoi, Domaas & Lied 1983): alpha = 0.96 beta - 1.4,
# SD 2.3 degrees. The beta point is where the profile slope first drops below 10 degrees and
# stays there for at least 30 m (AvaFrame com2AB's dsMin).
AB_SLOPE_K = 0.96
AB_OFFSET_DEG = -1.4
AB_SD_DEG = 2.3
BETA_SLOPE_DEG = 10.0
BETA_MIN_RUN_M = 30.0
# Below the beta test's own 10 degrees the regression would be extrapolating past the ground it
# was fit on, so a snow reach angle never drops under this.
ALPHA_FLOOR_DEG = 10.0


@dataclass(frozen=True)
class FlowProcess:
    """One mass-movement process and its published parameter set."""

    name: Literal["debris_flow", "snow_avalanche"]
    label: str
    # Tier A spreading.
    holmgren_exponent: float
    # Flow-Py remaps each neighbor's slope psi to Phi = (psi + 90 degrees) / 2 before raising
    # tan to the exponent (section 4.4). Flow-R uses tan(beta) directly (section 4.1).
    flow_py_terrain: bool
    persistence: tuple[float, float, float, float, float]
    # Tier A stopping. None means the reach angle comes from the alpha-beta model per path.
    reach_angle_deg: float | None
    v_max_ms: float | None
    # Tier B speed. None mu means the simplified friction-limited model (speed from Z_delta).
    mu: float | None = None
    xi_ms2: float | None = None
    flow_height_m: float | None = None
    citation: str = ""

    @property
    def z_delta_max_m(self) -> float:
        """The energy-line cap, V_max^2 / 2g. Infinite when the process has no V_max."""
        return math.inf if self.v_max_ms is None else self.v_max_ms**2 / (2 * G)

    @property
    def voellmy(self) -> bool:
        return self.mu is not None


# Section 10, Tier A table, debris-flow row, and section 4.3. Holmgren's exponent sits at the
# diffuse end, not Flow-R's 4-6: on this coarse 26 m grid a higher exponent collapses the
# flow into one gully cell, and the footprint must stay an area on the slope (project rule).
# Proportional persistence still gives the flow its inertia down the fall line.
DEBRIS_FLOW = FlowProcess(
    name="debris_flow",
    label="debris-flow",
    holmgren_exponent=1.1,
    flow_py_terrain=False,
    persistence=PERSISTENCE_PROPORTIONAL,
    reach_angle_deg=11.0,  # Flow-R's minimum travel angle for coarse and medium debris flows
    v_max_ms=15.0,  # Flow-R's usual cap: observed Swiss maxima were 13-14 m/s
    citation="Flow-R (Horton et al. 2013)",
)

# Section 10, Tier A snow-avalanche row, and Tier B defaults: Flow-Py exponent 8 on the
# remapped slope, cosine persistence, the alpha-beta reach angle one SD long (conservative),
# and a Voellmy sled with Buser & Frutiger's recommended mu 0.16, xi 1360 m/s^2, h 1 m.
SNOW_AVALANCHE = FlowProcess(
    name="snow_avalanche",
    label="snow-avalanche",
    holmgren_exponent=8.0,
    flow_py_terrain=True,
    persistence=PERSISTENCE_COSINE,
    reach_angle_deg=None,
    v_max_ms=None,
    mu=0.16,
    xi_ms2=1360.0,
    flow_height_m=1.0,
    citation="Flow-Py (D'Amboise et al. 2022), alpha-beta (Bakkehoi et al. 1983), Voellmy (Buser & Frutiger 1980)",
)


def process_for(kind: str | None) -> FlowProcess:
    """A mountain's runout is a snow avalanche; a hill's, or an unknown place's, is a debris flow."""
    return SNOW_AVALANCHE if kind == "mountain" else DEBRIS_FLOW


def terrain_weight(drop_m: float, step_m: float, process: FlowProcess) -> float:
    """Holmgren's unnormalized weight for a move to a lower neighbor (sections 4.1 and 4.4).

    Only lower neighbors are ever passed in: Flow-Py's remap would let flow climb flat or uphill
    cells, and this project's flow never runs uphill.
    """
    if process.flow_py_terrain:
        psi = math.atan2(drop_m, step_m)
        return math.tan((psi + math.pi / 2) / 2) ** process.holmgren_exponent
    return (drop_m / step_m) ** process.holmgren_exponent


def persistence_weight(cos_turn: float | None, table: tuple[float, ...]) -> float:
    """The persistence weight for a turn, linear between the table's 45-degree steps.

    cos_turn is the cosine of the angle between the incoming flow direction and the move.
    None means the cell has no incoming direction yet (the release), so every way is equal.
    """
    if cos_turn is None:
        return 1.0
    turn = math.degrees(math.acos(max(-1.0, min(1.0, cos_turn))))
    low = min(int(turn // 45), len(table) - 2)
    frac = (turn - 45 * low) / 45
    return table[low] + (table[low + 1] - table[low]) * frac


def energy_head(parent_head_m: float, drop_m: float, step_m: float, tan_alpha: float, cap_m: float) -> float:
    """Z_delta after one step (section 4.4): gain the drop, lose tan(alpha) per metre, keep under the cap.

    Carried along each path, this is Flow-R's energy balance per cell step (section 4.3) with
    V_max as the cap. A result at or below zero means the flow cannot reach that cell.
    """
    return min(parent_head_m + drop_m - tan_alpha * step_m, cap_m)


def head_speed(head_m: float) -> float:
    """The energy-line speed, v = sqrt(2 g Z_delta) (section 3.1)."""
    return math.sqrt(2 * G * head_m) if head_m > 0 else 0.0


def pcm_speed_sq(v0_sq: float, drop_m: float, step_m: float, mu: float, xi_ms2: float, flow_height_m: float) -> float:
    """Speed squared after one straight segment of a Voellmy sled, in PCM's closed form (5.1, 5.2).

    V^2 = a w (1 - e^b) + V0^2 e^b, a = g (sin beta - mu cos beta), b = -2 L / w, with L the
    segment's length along the slope and w = M/D = xi h / g. That is the exact solution of
    dv/dt = g (sin psi - mu cos psi) - g v^2 / (xi h) on a constant slope, so it stays stable at
    any cell size. The result can be negative: the sled stopped inside the segment.
    """
    beta = math.atan2(drop_m, step_m)
    length = math.hypot(drop_m, step_m)
    omega = xi_ms2 * flow_height_m / G
    a = G * (math.sin(beta) - mu * math.cos(beta))
    decay = math.exp(-2 * length / omega)
    # Where friction beats gravity (a < 0) the sled slows, and a negative result means it stopped.
    return a * omega * (1 - decay) + v0_sq * decay


def slope_turn_factor(slope_in_rad: float | None, slope_out_rad: float) -> float:
    """PCM's momentum correction at an abrupt slope decrease, V' = V cos(beta_i - beta_i+1) (5.2)."""
    if slope_in_rad is None or slope_out_rad >= slope_in_rad:
        return 1.0
    return math.cos(slope_in_rad - slope_out_rad)


def step_seconds(length_m: float, v_from: float, v_to: float) -> float:
    """Time over one step at the mean of its end speeds. Infinite if both ends are at rest."""
    mean = (v_from + v_to) / 2
    return length_m / mean if mean > 0 else math.inf


def beta_point(profile: list[tuple[float, float]]) -> int | None:
    """Index of the beta point on a (horizontal distance, height) profile from the release (3.2).

    The first point after which the slope stays under BETA_SLOPE_DEG for BETA_MIN_RUN_M.
    None when the profile never flattens that long.
    """
    limit = math.tan(math.radians(BETA_SLOPE_DEG))
    for i in range(1, len(profile) - 1):
        k = i
        flat = True
        # Walk on from i until the flat stretch covers BETA_MIN_RUN_M or the profile ends.
        while k + 1 < len(profile) and profile[k][0] - profile[i][0] < BETA_MIN_RUN_M:
            (s0, z0), (s1, z1) = profile[k], profile[k + 1]
            if s1 > s0 and (z0 - z1) / (s1 - s0) >= limit:
                flat = False
                break
            k += 1
        if flat and k > i:
            return i
    return None


def alpha_beta(profile: list[tuple[float, float]]) -> tuple[float, float, bool]:
    """The snow reach angle from a release profile: (alpha, beta, beta point found), in degrees.

    alpha = 0.96 beta - 1.4 - SD, one standard deviation long for a conservative runout, as the
    Tier A snow row recommends. Without a beta point on the profile, beta runs to its lowest
    point. alpha never drops below ALPHA_FLOOR_DEG.
    """
    index = beta_point(profile)
    found = index is not None
    if index is None:
        index = len(profile) - 1
    s0, z0 = profile[0]
    s, z = profile[index]
    beta = math.degrees(math.atan2(max(z0 - z, 0.0), max(s - s0, 1e-9))) if index > 0 else 0.0
    alpha = max(ALPHA_FLOOR_DEG, AB_SLOPE_K * beta + AB_OFFSET_DEG - AB_SD_DEG)
    return alpha, beta, found
