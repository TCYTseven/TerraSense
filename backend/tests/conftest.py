"""Shared test setup. Run from backend/: python -m pytest"""

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

STORM_FIXTURE = "backend/fixtures/open_meteo_storm.json"
# The demo's hazard, bypassed on the Golden Gate Trail. The two neighbors share an end point
# with the corridor, so the flagged run is mile 4.6 to 4.9.
SKYLINE_DEBRIS_MILES = (4.7, 4.8)
SKYLINE_DEBRIS_PROBABILITY = 0.82
SKYLINE_DEBRIS_WIDTH_M = 60


def storm_rain():
    """The synthetic storm fixture, loaded without leaving OPEN_METEO_FIXTURE set."""
    from app.weather import get_hourly_rain

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OPEN_METEO_FIXTURE", STORM_FIXTURE)
        return get_hourly_rain()


def with_skyline_debris(probability):
    """The real storm map plus a debris-flow corridor on the demo's flagged miles.

    The trained terrain model scores the whole Skyline loop near zero, so a real storm flags the
    valley trails and never the hero trail. The hazard-path tests (zone, bypass, persistence,
    posture) need a hazard on the hero trail, so they raise this one corridor on top of the map.
    """
    import numpy as np
    import shapely
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping

    from app.config import REPO_ROOT
    from app.ml.hazard import _grid_xy
    from app.ml.probability import ProbabilityMap

    features = json.loads((REPO_ROOT / "data" / "seed" / "trail_segments.geojson").read_text())["features"]
    low, high = SKYLINE_DEBRIS_MILES
    lines = [shapely.LineString(_grid_xy(f["geometry"]["coordinates"], probability.crs))
             for f in features if f["properties"]["start_mile"] >= low - 1e-6 and f["properties"]["end_mile"] <= high + 1e-6]
    corridor = shapely.union_all(lines).buffer(SKYLINE_DEBRIS_WIDTH_M)
    inside = geometry_mask([mapping(corridor)], out_shape=probability.values.shape,
                           transform=probability.transform, invert=True)
    values = probability.values.copy()
    values[inside] = np.fmax(values[inside], SKYLINE_DEBRIS_PROBABILITY)
    return ProbabilityMap(values, probability.transform, probability.crs, probability.method)


@pytest.fixture(scope="module")
def skyline_storm():
    """Score every map in the module as the storm plus the Skyline debris corridor."""
    from app.ml import probability

    score = probability.score
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(probability, "score", lambda rain=None: with_skyline_debris(score(rain)))
        yield


@pytest.fixture(scope="session")
def db_conn():
    """A connection to DATABASE_URL, or a skip when no database answers."""
    import psycopg

    from app.config import database_url

    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except (RuntimeError, psycopg.OperationalError) as exc:
        pytest.skip(f"no database: {exc}")
    yield conn
    conn.close()
