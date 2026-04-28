#!/usr/bin/env python3
"""Generate seed pools for SpeedFog Racing.

Calls the speedfog tool to generate seeds, then adds the racing mod DLL
to each seed's ME3 profile. Supports generating multiple pools
in parallel via a shared thread pool.

Usage:
    python generate_pool.py --pool standard --count 10 --game-dir "/path/to/ELDEN RING/Game"
    python generate_pool.py --pool sprint --pool standard --count 5 -j 3 --game-dir "/path"

Requires:
    - SPEEDFOG_PATH environment variable or --speedfog-path argument
    - speedfog_racing.dll in tools/assets/
    - uv installed (to run speedfog)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
import zipfile
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path
from typing import NamedTuple

import tomli_w

SCRIPT_DIR = Path(__file__).parent.resolve()
POOLS_DIR = SCRIPT_DIR / "pools"
DLL_NAME = "speedfog_racing.dll"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins for scalars/arrays."""
    result = {}
    for key in base.keys() | override.keys():
        if key in override and key in base:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        elif key in override:
            result[key] = override[key]
        else:
            result[key] = base[key]
    return result


def resolve_pool_config(
    pool_name: str,
    *,
    _pools_dir: Path | None = None,
    _seen: frozenset[str] | None = None,
) -> dict:
    """Resolve a pool config by following the extends chain.

    ``extends`` may be a single pool name or a list. Listed parents are
    merged left-to-right (later parents override earlier ones), then the
    pool's own values override all parents.

    Returns a fully-merged dict with no ``extends`` key.
    """
    pools_dir = _pools_dir or POOLS_DIR
    seen = _seen or frozenset()

    if pool_name in seen:
        raise ValueError(
            f"Circular extends detected: {' -> '.join(seen)} -> {pool_name}"
        )
    if len(seen) >= 6:
        raise ValueError(
            f"Extends chain too deep (max 6): {' -> '.join(seen)} -> {pool_name}"
        )

    toml_path = pools_dir / f"{pool_name}.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"Pool config not found: {toml_path}")

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    parents = data.pop("extends", None)
    if parents is None:
        return data
    if isinstance(parents, str):
        parents = [parents]

    merged: dict = {}
    for parent_name in parents:
        parent = resolve_pool_config(
            parent_name,
            _pools_dir=pools_dir,
            _seen=seen | {pool_name},
        )
        merged = deep_merge(merged, parent)
    return deep_merge(merged, data)


REQUIRED_SECTIONS = (
    "display",
    "run",
    "structure",
    "starting_items",
    "care_package",
    "item_randomizer",
    "enemy",
    "requirements",
    "budget",
)


def validate_pool_config(config: dict, pool_name: str) -> list[str]:
    """Validate a resolved pool config. Returns list of error messages."""
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in config:
            errors.append(f"{pool_name}: missing required section [{section}]")
        elif not isinstance(config[section], dict):
            errors.append(
                f"{pool_name}: [{section}] should be a table, got {type(config[section]).__name__}"
            )
    return errors


class SeedResult(NamedTuple):
    pool: str
    slug: str
    ok: bool
    duration: float  # seconds


class PoolSetup(NamedTuple):
    name: str
    config_path: Path
    output_dir: Path
    failed_dir: Path


def prepare_pool(pool_name: str, output_base: Path) -> PoolSetup:
    """Resolve config, create output dir, write config.toml for one pool."""
    output_pool_dir = output_base / pool_name
    output_pool_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_pool_config(pool_name)
    for err in validate_pool_config(resolved, pool_name):
        print(f"Warning: {err}")
    resolved_config = output_pool_dir / "config.toml"
    with open(resolved_config, "wb") as f:
        tomli_w.dump(resolved, f)

    return PoolSetup(
        name=pool_name,
        config_path=resolved_config,
        output_dir=output_pool_dir,
        failed_dir=output_base / f"{pool_name}_failed",
    )


def discover_pools() -> list[str]:
    """Discover available pool names from TOML files in the pools directory."""
    if not POOLS_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in POOLS_DIR.glob("*.toml") if not p.stem.startswith("_")
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    available_pools = discover_pools()

    parser = argparse.ArgumentParser(
        description="Generate seed pool for SpeedFog Racing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python generate_pool.py --pool standard --count 10 --game-dir "/mnt/games/ELDEN RING/Game"
    python generate_pool.py --pool sprint --pool standard --count 5 --game-dir "/path/to/game"
    python generate_pool.py --pool standard --dump
        """,
    )
    parser.add_argument(
        "--pool",
        required=True,
        action="append",
        choices=available_pools,
        help=f"Pool name, repeatable ({', '.join(available_pools)})",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Number of seeds to generate (required unless --dump)",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        help="Path to Elden Ring Game directory (required unless --dump)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Resolve and print the pool config TOML, then exit (no generation)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRIPT_DIR / "output",
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--speedfog-path",
        type=Path,
        default=None,
        help="Path to speedfog repository (default: SPEEDFOG_PATH env var)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, sequential)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show speedfog output in real-time",
    )
    return parser.parse_args()


def get_speedfog_path(args: argparse.Namespace) -> Path:
    """Get the speedfog repository path from args or environment."""
    if args.speedfog_path:
        return args.speedfog_path.resolve()

    env_path = os.environ.get("SPEEDFOG_PATH")
    if env_path:
        return Path(env_path).resolve()

    # Default: assume speedfog is a sibling directory
    default_path = SCRIPT_DIR.parent.parent / "speedfog"
    if default_path.exists():
        return default_path.resolve()

    print("Error: SPEEDFOG_PATH not set and speedfog not found at default location")
    print("Set SPEEDFOG_PATH or use --speedfog-path")
    sys.exit(1)


def run_speedfog(
    speedfog_path: Path,
    config_path: Path,
    output_dir: Path,
    game_dir: Path,
    *,
    verbose: bool = False,
) -> Path | None:
    """Run speedfog to generate a single seed.

    Returns the path to the generated seed directory, or None on failure.
    Stdout/stderr are always captured to ``output_dir/generation.log``.
    If verbose is True, output is also printed to the terminal.
    """
    log_path = output_dir / "generation.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        try:
            proc = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "speedfog",
                    str(config_path.absolute()),
                    "-o",
                    str(output_dir),
                    "--logs",
                    "--game-dir",
                    str(game_dir),
                ],
                cwd=speedfog_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as e:
            print(f"  Error starting speedfog: {e}")
            return None
        with proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                log_file.write(line)
                if verbose:
                    print(line, end="")

    if proc.returncode != 0:
        print(f"  Error running speedfog (exit code {proc.returncode})")
        return None

    # Find the generated seed directory (should be a single numeric directory)
    seed_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    if len(seed_dirs) == 1:
        return seed_dirs[0]

    print(f"  Warning: Expected 1 seed directory, found {len(seed_dirs)}")
    return None


def copy_mod_dll(seed_dir: Path, dll_source: Path) -> bool:
    """Copy the racing mod DLL to the seed's lib directory.

    Returns True on success, False on failure.
    """
    lib_dir = seed_dir / "lib"
    if not lib_dir.exists():
        lib_dir.mkdir(parents=True)

    dll_dest = lib_dir / DLL_NAME
    try:
        shutil.copy2(dll_source, dll_dest)
        return True
    except OSError as e:
        print(f"  Error copying DLL: {e}")
        return False


def add_dll_to_me3_config(seed_dir: Path) -> bool:
    """Add the racing mod DLL to config_speedfog.me3's natives.

    ME3 loads native DLLs from ``[[natives]]`` entries. The base SpeedFog
    package only knows about its own helper DLLs, so the racing overlay DLL
    must be registered after it is copied to ``lib/``.
    Returns True on success, False on failure.
    """
    config_path = seed_dir / "me3" / "config_speedfog.me3"
    dll_path = f"../lib/{DLL_NAME}"

    if not config_path.exists():
        print("  Error: me3/config_speedfog.me3 not found")
        return False

    try:
        content = config_path.read_text(encoding="utf-8")

        if dll_path in content:
            return True

        native_entry = f'[[natives]]\npath = "{dll_path}"'
        supports_match = re.search(
            r'(\[\[supports\]\]\s*\ngame\s*=\s*"eldenring"\s*)',
            content,
        )

        if supports_match:
            insert_at = supports_match.end()
            new_content = (
                content[:insert_at]
                + f"{native_entry}\n\n"
                + content[insert_at:].lstrip("\n")
            )
        else:
            new_content = content.rstrip() + f"\n{native_entry}\n"

        config_path.write_text(new_content, encoding="utf-8")
        return True

    except OSError as e:
        print(f"  Error modifying ME3 config: {e}")
        return False


def add_dll_to_legacy_config(seed_dir: Path) -> bool:
    """Add the racing mod DLL to config_speedfog.toml's external_dlls."""
    config_path = seed_dir / "config_speedfog.toml"

    if not config_path.exists():
        print("  Error: config_speedfog.toml not found")
        return False

    try:
        content = config_path.read_text(encoding="utf-8")
        dll_entry = f'    "lib\\\\{DLL_NAME}",'
        pattern = r"(external_dlls\s*=\s*\[)([^\]]*?)(\])"

        def add_dll(match: re.Match[str]) -> str:
            prefix = match.group(1)
            existing = match.group(2)
            suffix = match.group(3)

            if DLL_NAME in existing:
                return match.group(0)

            if existing.strip():
                existing = existing.rstrip()
                if not existing.endswith(","):
                    existing += ","
                return f"{prefix}{existing}\n{dll_entry}\n{suffix}"
            return f"{prefix}\n{dll_entry}\n{suffix}"

        new_content, count = re.subn(pattern, add_dll, content)

        if count == 0:
            print("  Error: Could not find external_dlls in config")
            return False

        config_path.write_text(new_content, encoding="utf-8")
        return True

    except OSError as e:
        print(f"  Error modifying config: {e}")
        return False


def add_dll_to_config(seed_dir: Path) -> bool:
    """Add the racing mod DLL to the generated launcher config.

    Prefer the current ME3 profile, with a legacy ModEngine 2 fallback for
    old generated seeds kept around for debugging or migration.
    """
    if (seed_dir / "me3" / "config_speedfog.me3").exists():
        return add_dll_to_me3_config(seed_dir)
    return add_dll_to_legacy_config(seed_dir)


def zip_seed_dir(seed_dir: Path, output_zip: Path, top_dir: str) -> None:
    """Create a zip archive from a seed directory.

    All files are placed under a top-level directory inside the zip
    (e.g., speedfog_abc123/lib/...).
    """
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(seed_dir.rglob("*")):
            if file_path.is_file():
                arcname = f"{top_dir}/{file_path.relative_to(seed_dir)}"
                zf.write(file_path, arcname)


def ensure_helper_config(seed_dir: Path) -> None:
    """Ensure RandomizerHelper_config.ini exists in lib/ with racing defaults.

    RandomizerHelper.dll is always present in lib/ (copied by speedfog's
    PackagingWriter) but its config may be missing if item randomizer was
    disabled or failed. Without the config, the DLL uses defaults that
    include unwanted features like auto-equip.
    """
    config_path = seed_dir / "lib" / "RandomizerHelper_config.ini"
    if config_path.exists():
        return

    config_path.write_text(
        "[settings]\n"
        "autoEquip = false\n"
        "equipShop = false\n"
        "equipWeapons = false\n"
        "bowLeft = false\n"
        "castLeft = false\n"
        "equipArmor = false\n"
        "equipAccessory = false\n"
        "equipSpells = false\n"
        "equipCrystalTears = false\n"
        "autoUpgrade = true\n"
        "autoUpgradeWeapons = true\n"
        "regionLockWeapons = false\n"
        "autoUpgradeSpiritAshes = true\n"
        "autoUpgradeDropped = true\n",
        encoding="utf-8",
    )
    print("  Added default RandomizerHelper_config.ini to lib/")


def process_seed(
    seed_dir: Path,
    dll_source: Path,
    output_pool_dir: Path,
    seed_slug: str,
) -> bool:
    """Post-process a generated seed: add DLL, modify config, zip to output.

    Returns True on success, False on failure.
    """
    # Copy the mod DLL
    if not copy_mod_dll(seed_dir, dll_source):
        return False

    # Modify me3/config_speedfog.me3 (or legacy configs)
    if not add_dll_to_config(seed_dir):
        return False

    # Ensure RandomizerHelper has safe defaults even if item rando was
    # disabled or failed (the DLL is always present in lib/)
    ensure_helper_config(seed_dir)

    # Zip to final location with seed_<slug>.zip naming
    final_zip = output_pool_dir / f"seed_{seed_slug}.zip"
    top_dir = f"speedfog_{seed_slug}"

    try:
        zip_seed_dir(seed_dir, final_zip, top_dir)
        return True
    except OSError as e:
        print(f"  Error creating seed zip: {e}")
        final_zip.unlink(missing_ok=True)
        return False


def generate_one_seed(
    index: int,
    total: int,
    pool_name: str,
    speedfog_path: Path,
    pool_config: Path,
    game_dir: Path,
    dll_source: Path,
    output_pool_dir: Path,
    failed_dir: Path,
    *,
    verbose: bool = False,
) -> SeedResult:
    """Generate and process a single seed."""
    seed_slug = uuid.uuid4().hex[:12]
    prefix = f"[{pool_name} {index}/{total}]"
    print(f"{prefix} Generating seed_{seed_slug}...")

    t0 = time.monotonic()
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)
    ok = False

    try:
        seed_dir = run_speedfog(
            speedfog_path,
            pool_config,
            temp_path,
            game_dir,
            verbose=verbose,
        )
        if seed_dir is None:
            print(f"{prefix} Failed: speedfog generation error")
            return SeedResult(pool_name, seed_slug, False, time.monotonic() - t0)

        if process_seed(seed_dir, dll_source, output_pool_dir, seed_slug):
            print(f"{prefix} Success: seed_{seed_slug}.zip")
            ok = True
            return SeedResult(pool_name, seed_slug, True, time.monotonic() - t0)
        else:
            print(f"{prefix} Failed: post-processing error")
            return SeedResult(pool_name, seed_slug, False, time.monotonic() - t0)
    finally:
        if ok:
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif temp_path.exists() and any(temp_path.iterdir()):
            failed_dir.mkdir(parents=True, exist_ok=True)
            fail_dest = failed_dir / f"seed_{seed_slug}"
            if fail_dest.exists():
                shutil.rmtree(fail_dest)
            shutil.move(str(temp_path), str(fail_dest))
            print(f"{prefix} Kept for investigation: {fail_dest}")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    """Main entry point.

    Exit codes:
        0 - All seeds generated successfully
        1 - Total failure (no seeds generated)
        2 - Partial failure (some seeds generated, some failed)
    """
    args = parse_args()

    # Deduplicate pools preserving order
    args.pool = list(dict.fromkeys(args.pool))

    # --dump: resolve and print pool config, then exit
    if args.dump:
        for i, pool_name in enumerate(args.pool):
            if len(args.pool) > 1:
                print(f"# --- {pool_name} ---")
            resolved = resolve_pool_config(pool_name)
            sys.stdout.buffer.write(tomli_w.dumps(resolved).encode())
            if i < len(args.pool) - 1:
                print()
        return 0

    # Validate required args for generation mode
    if args.count is None:
        print("Error: --count is required (unless using --dump)")
        return 1
    if args.game_dir is None:
        print("Error: --game-dir is required (unless using --dump)")
        return 1

    # Validate count
    if args.count <= 0:
        print("Error: --count must be a positive integer")
        return 1

    if args.jobs <= 0:
        print("Error: --jobs must be a positive integer")
        return 1

    # Validate paths
    speedfog_path = get_speedfog_path(args)
    if not speedfog_path.exists():
        print(f"Error: Speedfog path does not exist: {speedfog_path}")
        return 1

    dll_source = SCRIPT_DIR / "assets" / DLL_NAME
    if not dll_source.exists():
        print(f"Error: DLL not found: {dll_source}")
        print("Run ./tools/download-mod.sh to fetch it from GitHub Actions")
        return 1

    if not args.game_dir.exists():
        print(f"Error: Game directory does not exist: {args.game_dir}")
        return 1

    # Prepare all pools (resolve configs, create output dirs)
    pools = [prepare_pool(pool_name, args.output) for pool_name in args.pool]

    # Build flat list of work items across all pools
    work_items = [
        (pool_setup, i + 1) for pool_setup in pools for i in range(args.count)
    ]
    total_seeds = len(work_items)
    jobs = min(args.jobs, total_seeds)

    if len(pools) == 1:
        print(
            f"Generating {args.count} seeds for pool '{pools[0].name}' ({jobs} workers)"
        )
    else:
        print(
            f"Generating {args.count} seeds x {len(pools)} pools"
            f" = {total_seeds} total ({jobs} workers)"
        )
        print(f"  Pools: {', '.join(p.name for p in pools)}")
    print(f"  Speedfog: {speedfog_path}")
    print(f"  Game: {args.game_dir}")
    print(f"  Output: {args.output}")
    print()

    results: list[SeedResult] = []

    t_start = time.monotonic()

    if jobs == 1:
        for pool_setup, idx in work_items:
            results.append(
                generate_one_seed(
                    index=idx,
                    total=args.count,
                    pool_name=pool_setup.name,
                    speedfog_path=speedfog_path,
                    pool_config=pool_setup.config_path,
                    game_dir=args.game_dir,
                    dll_source=dll_source,
                    output_pool_dir=pool_setup.output_dir,
                    failed_dir=pool_setup.failed_dir,
                    verbose=args.verbose,
                )
            )
    else:
        if args.verbose:
            print("Warning: --verbose output may interleave with multiple jobs")

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {}
            for pool_setup, idx in work_items:
                fut = executor.submit(
                    generate_one_seed,
                    index=idx,
                    total=args.count,
                    pool_name=pool_setup.name,
                    speedfog_path=speedfog_path,
                    pool_config=pool_setup.config_path,
                    game_dir=args.game_dir,
                    dll_source=dll_source,
                    output_pool_dir=pool_setup.output_dir,
                    failed_dir=pool_setup.failed_dir,
                    verbose=args.verbose,
                )
                futures[fut] = (pool_setup.name, idx)
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    pname, idx = futures[future]
                    print(f"Unexpected error in seed worker [{pname} {idx}]: {e}")
                    results.append(SeedResult(pname, "error", False, 0.0))

    total_time = time.monotonic() - t_start

    # Group results by pool
    pool_results: dict[str, list[SeedResult]] = {p.name: [] for p in pools}
    for r in results:
        pool_results[r.pool].append(r)

    all_succeeded = 0
    all_failed = 0

    print()
    for pool_name in args.pool:
        pr = pool_results[pool_name]
        succeeded = sum(1 for r in pr if r.ok)
        failed = len(pr) - succeeded
        all_succeeded += succeeded
        all_failed += failed

        print(f"  Pool: {pool_name}")
        print(f"  {'Seed':<20} {'Status':<10} {'Time':>6}")
        print("  " + "-" * 38)
        for r in pr:
            status = "OK" if r.ok else "FAILED"
            print(f"  seed_{r.slug:<14} {status:<10} {_fmt_duration(r.duration):>6}")
        print(f"  {succeeded} succeeded, {failed} failed")
        failed_dir = args.output / f"{pool_name}_failed"
        if failed > 0 and failed_dir.exists():
            print(f"  Failed seeds preserved in: {failed_dir}")
        print()

    if len(pools) > 1:
        print("  " + "=" * 38)
        print(
            f"  Total: {all_succeeded} succeeded, {all_failed} failed"
            f" in {_fmt_duration(total_time)}"
        )

    if all_failed > 0 and all_succeeded == 0:
        return 1  # total failure
    if all_failed > 0:
        return 2  # partial failure (some seeds generated)
    return 0


def _fmt_duration(seconds: float) -> str:
    """Format a duration as e.g. '1m32s', '45s', or '<1s'."""
    if seconds < 1:
        return "<1s"
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


if __name__ == "__main__":
    sys.exit(main())
