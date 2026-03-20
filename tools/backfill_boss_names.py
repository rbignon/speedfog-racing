#!/usr/bin/env python3
"""Backfill boss_name and randomized_bosses on existing seed graph_json.

Patches each seed's graph_json nodes:
- boss_name: canonical name (from randomized_boss, enemy.txt mapping, or display_name)
- randomized_bosses: converts old randomized_boss string to a single-element list

Usage:
    cd server && uv run python ../tools/backfill_boss_names.py
    cd server && uv run python ../tools/backfill_boss_names.py --dry-run
    cd server && uv run python ../tools/backfill_boss_names.py --enemy-txt /path/to/enemy.txt
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Must run from server/ directory (cd server && uv run python ../tools/backfill_boss_names.py)
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(Path.cwd()))

from speedfog_racing.config import settings  # noqa: E402
from speedfog_racing.models import Seed  # noqa: E402

_PHASE_SUFFIX_RE = re.compile(r" \d+$")
_BOSS_TYPES = {"major_boss", "final_boss"}


def parse_boss_names(enemy_txt_path: Path) -> dict[int, str]:
    """Parse enemy.txt to build DefeatFlag -> boss name mapping."""
    if not enemy_txt_path.exists():
        return {}

    boss_classes = {
        "Boss",
        "MinorBoss",
        "Miniboss",
        "Evergaol",
        "DragonMiniboss",
        "NightMiniboss",
    }

    with open(enemy_txt_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    boss_names: dict[int, str] = {}
    for entry in data.get("Enemies", []):
        defeat_flag = entry.get("DefeatFlag")
        extra_name = entry.get("ExtraName")
        entry_class = entry.get("Class", "")
        if not defeat_flag or not extra_name or entry_class not in boss_classes:
            continue
        clean_name = _PHASE_SUFFIX_RE.sub("", extra_name)
        boss_names[int(defeat_flag)] = clean_name

    return boss_names


def patch_seed_graph(graph_json: dict, boss_names: dict[int, str]) -> tuple[dict, int]:
    """Patch graph_json nodes with boss_name and randomized_bosses."""
    nodes = graph_json.get("nodes", {})
    patched_count = 0

    for node in nodes.values():
        changed = False

        # Convert randomized_boss (str) -> randomized_bosses (list)
        old_randomized = node.pop("randomized_boss", None)
        if old_randomized and "randomized_bosses" not in node:
            node["randomized_bosses"] = [old_randomized]
            changed = True

        # Add boss_name if missing
        if "boss_name" not in node:
            node_type = node.get("type", "")

            # Priority 1: from randomized_bosses (phase 2 = last element)
            randomized_list = node.get("randomized_bosses")
            if randomized_list:
                node["boss_name"] = _PHASE_SUFFIX_RE.sub("", randomized_list[-1])
                changed = True
            else:
                # Priority 2: defeat_flag -> enemy.txt mapping
                defeat_flag = node.get("defeat_flag", 0)
                if defeat_flag and defeat_flag in boss_names:
                    node["boss_name"] = boss_names[defeat_flag]
                    changed = True
                # Priority 3: fallback for boss-type nodes
                elif node_type in _BOSS_TYPES:
                    display = node.get("display_name", "")
                    if display:
                        node["boss_name"] = display.rsplit(" - ", 1)[-1]
                        changed = True

        if changed:
            patched_count += 1

    return graph_json, patched_count


async def backfill(enemy_txt_path: Path, dry_run: bool = False) -> None:
    """Run the backfill."""
    boss_names = parse_boss_names(enemy_txt_path)
    print(f"Loaded {len(boss_names)} boss names from enemy.txt")

    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_maker() as db:
        seeds = (await db.execute(select(Seed))).scalars().all()
        print(f"Found {len(seeds)} seeds to check")

        total_patched = 0
        seeds_modified = 0

        for seed in seeds:
            patched_graph, count = patch_seed_graph(seed.graph_json, boss_names)
            if count > 0:
                total_patched += count
                seeds_modified += 1
                if not dry_run:
                    await db.execute(
                        update(Seed)
                        .where(Seed.id == seed.id)
                        .values(graph_json=patched_graph)
                    )

        if not dry_run:
            await db.commit()

        action = "Would patch" if dry_run else "Patched"
        print(f"{action} {total_patched} nodes across {seeds_modified} seeds")

    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill boss_name in seed graph_json"
    )
    parser.add_argument(
        "--enemy-txt",
        type=Path,
        default=SCRIPT_DIR.parent.parent / "speedfog" / "data" / "enemy.txt",
        help="Path to enemy.txt (default: ../../speedfog/data/enemy.txt)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be patched without modifying the database",
    )
    args = parser.parse_args()

    if not args.enemy_txt.exists():
        print(f"Error: enemy.txt not found at {args.enemy_txt}", file=sys.stderr)
        return 1

    asyncio.run(backfill(args.enemy_txt, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
