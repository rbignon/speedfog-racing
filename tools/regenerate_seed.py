#!/usr/bin/env python3
"""Regenerate a seed's zip from its database row, e.g. a purged speedrun seed.

Finds the seed in the local database by its seed number, as its seed page
does, and reads its pool and stored graph; reruns speedfog on the current
checkout with the graph's RNG seed and the pool's current config; writes
``seed_<seed_number>.zip`` only when the regenerated graph.json matches the
stored one. A generator or pool change that
alters the graph makes it fail: the seed then cannot be restored this way.

The ``plugins`` block is compared but never blocks: it mirrors the pool's
``[plugin.*]`` tables, which are switched on and off over time, while the rest
of the graph is the run itself. Its differences are printed as warnings.

Usage (from server/, which holds the database settings):
    cd server && uv run python ../tools/regenerate_seed.py <seed-number> \\
        --game-dir "/path/to/ELDEN RING/Game"

Requires the same tools as generate_pool.py (speedfog checkout, uv, game
files). The zip lands in tools/output/restored/<pool>/ by default; copying it
back to the seed's folder_path on the server makes the seed replayable again.
See docs/SEED_PIPELINE.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

from generate_pool import (
    SCRIPT_DIR,
    get_speedfog_path,
    prepare_pool,
    process_seed,
    run_speedfog,
)

# Top-level graph keys whose differences are reported but do not fail the run.
WARN_ONLY_KEYS = ("plugins",)
MAX_PRINTED_DIFFERENCES = 20


class StoredSeed(NamedTuple):
    seed_number: str
    pool_name: str
    graph_json: dict[str, Any]
    folder_path: str


class SeedNotFoundError(Exception):
    """No seed, or several, match the given seed number."""


def _short(value: Any, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def json_differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Where two JSON values differ, one line per path (``expected`` being the
    database's graph, ``actual`` the regenerated one)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(expected.keys() | actual.keys()):
            sub = f"{path}.{key}" if path else key
            if key not in actual:
                out.append(f"{sub}: missing from the regenerated graph")
            elif key not in expected:
                out.append(f"{sub}: missing from the database graph")
            else:
                out.extend(json_differences(expected[key], actual[key], sub))
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [
                f"{path}: {len(expected)} items in the database,"
                f" {len(actual)} regenerated"
            ]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out.extend(json_differences(e, a, f"{path}[{i}]"))
        return out
    if expected != actual:
        return [
            f"{path}: {_short(expected)} in the database, {_short(actual)} regenerated"
        ]
    return []


def compare_graphs(
    db_graph: dict[str, Any], regenerated: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """(errors, warnings): differences outside WARN_ONLY_KEYS, then inside."""

    def split(graph: dict[str, Any], warn_only: bool) -> dict[str, Any]:
        return {k: v for k, v in graph.items() if (k in WARN_ONLY_KEYS) == warn_only}

    errors = json_differences(split(db_graph, False), split(regenerated, False))
    warnings = json_differences(split(db_graph, True), split(regenerated, True))
    return errors, warnings


async def load_seed(seed_number: str) -> StoredSeed:
    """The seed named by ``seed_number`` as its seed page finds it (the full
    number or a unique prefix, among played seeds outside training pools),
    read through the server's settings (server/.env)."""
    # Imported here so the comparison helpers load without the server package.
    from speedfog_racing.database import engine, get_db_context
    from speedfog_racing.services.set_seed_service import (
        SEED_PREFIX_MIN,
        SeedLookupError,
        resolve_seed,
    )

    try:
        async with get_db_context() as db:
            try:
                seed = await resolve_seed(db, seed_number)
            except SeedLookupError as e:
                if e.kind == "ambiguous":
                    raise SeedNotFoundError(
                        f"{seed_number!r} matches several seeds: give more characters"
                    ) from e
                raise SeedNotFoundError(
                    f"no played seed {seed_number!r} outside training pools"
                    f" in the database (a prefix needs {SEED_PREFIX_MIN}+ characters)"
                ) from e
            return StoredSeed(
                seed.seed_number, seed.pool_name, seed.graph_json, seed.folder_path
            )
    finally:
        await engine.dispose()


def speedfog_commit(speedfog_path: Path) -> str:
    """HEAD's short hash and subject, flagged when tracked files have local
    changes (they may alter the seed in ways the graph does not show)."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(speedfog_path), *args], capture_output=True, text=True
        )

    head = git("log", "-1", "--format=%h %s")
    if head.returncode != 0:
        return "unknown commit"
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    return head.stdout.strip() + (", with uncommitted changes" if dirty else "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate a seed's zip and check its graph against the database"
    )
    parser.add_argument(
        "seed_number",
        help="Seed number as on its seed page (seeds.seed_number), or a unique"
        " prefix of 6+ characters",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        required=True,
        help="Path to Elden Ring Game directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRIPT_DIR / "output" / "restored",
        help="Output directory (default: tools/output/restored)",
    )
    parser.add_argument(
        "--speedfog-path",
        type=Path,
        default=None,
        help="Path to speedfog repository (default: SPEEDFOG_PATH env var)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show speedfog output in real-time",
    )
    return parser.parse_args()


def _print_differences(title: str, lines: list[str]) -> None:
    print(f"{title} ({len(lines)}):")
    for line in lines[:MAX_PRINTED_DIFFERENCES]:
        print(f"  {line}")
    if len(lines) > MAX_PRINTED_DIFFERENCES:
        print(f"  ... and {len(lines) - MAX_PRINTED_DIFFERENCES} more")


def main() -> int:
    args = parse_args()

    try:
        seed = asyncio.run(load_seed(args.seed_number))
    except SeedNotFoundError as e:
        print(f"Error: {e}")
        return 1
    rng_seed = seed.graph_json.get("seed")
    if not isinstance(rng_seed, int) or rng_seed <= 0:
        print(f"Error: the stored graph has no usable RNG seed ({rng_seed!r})")
        return 1

    speedfog_path = get_speedfog_path(args)
    if not speedfog_path.exists():
        print(f"Error: Speedfog path does not exist: {speedfog_path}")
        return 1
    if not args.game_dir.exists():
        print(f"Error: Game directory does not exist: {args.game_dir}")
        return 1
    try:
        pool = prepare_pool(seed.pool_name, args.output)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    print(f"Seed {seed.seed_number} (pool {seed.pool_name}), RNG seed {rng_seed}")
    print(f"  Speedfog: {speedfog_path} ({speedfog_commit(speedfog_path)})")
    print("Generating (a few minutes)...")

    temp_path = Path(tempfile.mkdtemp())
    ok = False
    try:
        seed_dir = run_speedfog(
            speedfog_path,
            pool.config_path,
            temp_path,
            args.game_dir,
            verbose=args.verbose,
            seed=rng_seed,
        )
        if seed_dir is None:
            print("Error: speedfog generation failed")
            return 1

        regenerated = json.loads((seed_dir / "graph.json").read_text(encoding="utf-8"))
        errors, warnings = compare_graphs(seed.graph_json, regenerated)
        if warnings:
            _print_differences(
                "Warning: plugin settings differ from the original seed", warnings
            )
        if errors:
            _print_differences(
                "Error: the regenerated graph differs from the database", errors
            )
            return 1
        print("Graph identical to the database.")

        if not process_seed(seed_dir, pool.output_dir, seed.seed_number):
            print("Error: post-processing failed")
            return 1
        ok = True
    finally:
        if ok:
            shutil.rmtree(temp_path, ignore_errors=True)
        else:
            fail_dest = pool.failed_dir / f"seed_{seed.seed_number}"
            if fail_dest.exists():
                shutil.rmtree(fail_dest)
            pool.failed_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_path), str(fail_dest))
            print(f"Kept for investigation: {fail_dest}")

    zip_path = pool.output_dir / f"seed_{seed.seed_number}.zip"
    remote_tmp = f"/tmp/{zip_path.name}"
    target = seed.folder_path
    print(f"Done: {zip_path}")
    print("Copy it back to the server (the seed turns replayable within a cache TTL):")
    print(f'  scp "{zip_path}" "$DEPLOY_HOST:{remote_tmp}"')
    # The local database cannot tell whether prod still has the original zip:
    # never overwrite it.
    print(
        f'  ssh "$DEPLOY_HOST" \'if [ -e {target} ]; then echo {target} already exists;'
        f" else sudo -u speedfog cp {remote_tmp} {target}; fi; rm {remote_tmp}'"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
