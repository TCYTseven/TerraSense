#!/usr/bin/env python3
"""Build one mountain's full data pack (implementation step 32).

Runs the Rainier pipeline's scripts in order for one pack from ml/scripts/mountain_packs.py:

  1. download_sources.py   DEM and WorldCover windows, NASA GLC points (may be empty)
  2. build_features.py     the seven-band 30 m stack in the peak's UTM zone
  3. train_susceptibility. the knowledge-driven index (packs never train; Rainier's labels stay home)
  4. render_tiles.py       XYZ tiles under backend/tiles/<slug>/susceptibility/
  5. import_trails.py      OpenStreetMap trails via Overture, hero mile segments
  6. build_trail_network.py  the bypass network, skipped when the box has no named trail

Each stage skips work whose output already exists, so a rerun after a failure continues
where it stopped. The committed outputs land in data/seed/packs/<slug>/; the rasters and
tiles are gitignored and rebuild from this one command.

Run from the repo root:
  python ml/scripts/build_pack.py mount-fuji [--force]
  python ml/scripts/build_pack.py --all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import mountain_packs as mp

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent


def run(script: str, *extra: str) -> None:
    command = [sys.executable, str(SCRIPTS / script), *extra]
    print(f"\n=== {script} {' '.join(extra)}")
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def build(slug: str, force: bool) -> None:
    pack, paths = mp.get(slug), mp.paths(slug)
    print(f"### {pack.name} ({slug}): bbox {list(pack.bbox)}, grid {pack.utm_crs}")
    forced = ["--force"] if force else []
    run("download_sources.py", "--mountain", slug, *forced)
    run("build_features.py", "--mountain", slug)
    run("train_susceptibility.py", "--mountain", slug)
    run("render_tiles.py", "--mountain", slug)
    run("import_trails.py", "--mountain", slug, *forced)
    hero_segments = json.loads(paths.hero_segments.read_text(encoding="utf-8"))["features"]
    if hero_segments:
        run("build_trail_network.py", "--mountain", slug)
    else:
        print(f"\n=== build_trail_network.py skipped: {slug} has no hero trail to route a bypass on")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one mountain's full data pack.")
    parser.add_argument("slug", nargs="?", help="pack slug from mountain_packs.py")
    parser.add_argument("--all", action="store_true", help="build every pack except Rainier")
    parser.add_argument("--force", action="store_true", help="refresh the downloads and the Overture cache")
    args = parser.parse_args()
    if bool(args.slug) == args.all:
        parser.error("pass one slug, or --all")
    slugs = [s for s in mp.PACKS if s != mp.RAINIER_SLUG] if args.all else [args.slug]

    failed = []
    for slug in slugs:
        try:
            build(slug, args.force)
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
            failed.append(slug)
            print(f"### {slug} FAILED: {exc}", file=sys.stderr)
    if failed:
        print(f"packs with failures: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nAll packs built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
