#!/usr/bin/env python3
"""Write data/seed/mountains.json via backend/app/mountain_catalog.py (Wikidata, else Overpass).

From the repo root:

    python ml/scripts/fetch_mountains_wikidata.py
    cd backend && python -m app.seed
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "app.mountain_catalog", "--write-seed"],
        cwd=BACKEND,
        check=True,
    )


if __name__ == "__main__":
    main()
