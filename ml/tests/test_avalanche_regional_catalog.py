from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

from download_avalanche_regional_catalog import page_url  # noqa: E402


def test_regional_catalog_query_is_bounded_and_as_of() -> None:
    url = page_url(
        "avalanche_observation",
        start_date="2023-10-25",
        end_date="2026-07-20",
        bbox="-125,42,-116,49.1",
        page=3,
        page_size=100,
    )
    assert "date%5Bgte%5D=2023-10-25" in url
    assert "date%5Blte%5D=2026-07-20" in url
    assert "page=3" in url and "page_size=100" in url
    assert "bbox=-125%2C42%2C-116%2C49.1" in url
