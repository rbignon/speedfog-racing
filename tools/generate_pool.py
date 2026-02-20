#!/usr/bin/env python3
"""Generate seed pool for SpeedFog Racing.

Calls the speedfog tool to generate seeds, then adds the racing mod DLL
to each seed's ModEngine configuration.

Usage:
    python generate_pool.py --pool standard --count 10 --game-dir "/path/to/ELDEN RING/Game"

Requires:
    - SPEEDFOG_PATH environment variable or --speedfog-path argument
    - speedfog_race_mod.dll in tools/assets/
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
import uuid
import zipfile
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
POOLS_DIR = SCRIPT_DIR / "pools"
DLL_NAME = "speedfog_race_mod.dll"


def discover_pools() -> list[str]:
    """Discover available pool names from TOML files in the pools directory."""
    if not POOLS_DIR.is_dir():
        return []
    return sorted(p.stem for p in POOLS_DIR.glob("*.toml"))


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    available_pools = discover_pools()

    parser = argparse.ArgumentParser(
        description="Generate seed pool for SpeedFog Racing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python generate_pool.py --pool standard --count 10 --game-dir "/mnt/games/ELDEN RING/Game"
    python generate_pool.py --pool sprint --count 5 --game-dir "C:/Games/ELDEN RING/Game" --output ./seeds
        """,
    )
    parser.add_argument(
        "--pool",
        required=True,
        choices=available_pools,
        help=f"Pool name ({', '.join(available_pools)})",
    )
    parser.add_argument(
        "--count",
        required=True,
        type=int,
        help="Number of seeds to generate",
    )
    parser.add_argument(
        "--game-dir",
        required=True,
        type=Path,
        help="Path to Elden Ring Game directory",
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
    If verbose is True, output is streamed in real-time to the terminal.
    """
    try:
        subprocess.run(
            [
                "uv",
                "run",
                "speedfog",
                str(config_path.absolute()),
                "-o",
                str(output_dir),
                "--spoiler",
                "--game-dir",
                str(game_dir),
            ],
            cwd=speedfog_path,
            check=True,
            stdout=None if verbose else subprocess.DEVNULL,
            stderr=None if verbose else subprocess.DEVNULL,
        )

        # Find the generated seed directory (should be a single numeric directory)
        seed_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        if len(seed_dirs) == 1:
            return seed_dirs[0]

        print(f"  Warning: Expected 1 seed directory, found {len(seed_dirs)}")
        return None

    except subprocess.CalledProcessError as e:
        print(f"  Error running speedfog (exit code {e.returncode})")
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


def add_dll_to_config(seed_dir: Path) -> bool:
    """Add the racing mod DLL to config_speedfog.toml's external_dlls.

    Uses string manipulation to avoid external TOML dependencies.
    Returns True on success, False on failure.
    """
    config_path = seed_dir / "config_speedfog.toml"

    if not config_path.exists():
        print("  Error: config_speedfog.toml not found")
        return False

    try:
        content = config_path.read_text(encoding="utf-8")

        # Find the external_dlls line and add our DLL
        # Pattern matches: external_dlls = [...]
        dll_entry = f'    "lib\\\\{DLL_NAME}",'

        # Look for existing external_dlls array
        pattern = r"(external_dlls\s*=\s*\[)([^\]]*?)(\])"

        def add_dll(match: re.Match[str]) -> str:
            prefix = match.group(1)
            existing = match.group(2)
            suffix = match.group(3)

            # Check if our DLL is already there
            if DLL_NAME in existing:
                return match.group(0)

            # Add our DLL to the array
            if existing.strip():
                # There are existing entries, add ours after the last one
                # Find the last entry and add ours after
                existing = existing.rstrip()
                if not existing.endswith(","):
                    existing += ","
                new_content = f"{prefix}{existing}\n{dll_entry}\n{suffix}"
            else:
                # Empty array, add our entry
                new_content = f"{prefix}\n{dll_entry}\n{suffix}"

            return new_content

        new_content, count = re.subn(pattern, add_dll, content)

        if count == 0:
            print("  Error: Could not find external_dlls in config")
            return False

        config_path.write_text(new_content, encoding="utf-8")
        return True

    except OSError as e:
        print(f"  Error modifying config: {e}")
        return False


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

    # Modify config_speedfog.toml
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
    speedfog_path: Path,
    pool_config: Path,
    game_dir: Path,
    dll_source: Path,
    output_pool_dir: Path,
    failed_dir: Path,
    *,
    verbose: bool = False,
) -> bool:
    """Generate and process a single seed. Returns True on success."""
    seed_slug = uuid.uuid4().hex[:12]
    prefix = f"[{index}/{total}]"
    print(f"{prefix} Generating seed_{seed_slug}...")

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
            return False

        if process_seed(seed_dir, dll_source, output_pool_dir, seed_slug):
            print(f"{prefix} Success: seed_{seed_slug}.zip")
            ok = True
            return True
        else:
            print(f"{prefix} Failed: post-processing error")
            return False
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

    pool_config = SCRIPT_DIR / "pools" / f"{args.pool}.toml"
    if not pool_config.exists():
        print(f"Error: Pool config not found: {pool_config}")
        return 1

    dll_source = SCRIPT_DIR / "assets" / DLL_NAME
    if not dll_source.exists():
        print(f"Error: DLL not found: {dll_source}")
        print("Run ./tools/download-mod.sh to fetch it from GitHub Actions")
        return 1

    if not args.game_dir.exists():
        print(f"Error: Game directory does not exist: {args.game_dir}")
        return 1

    # Create output directory
    output_pool_dir = args.output / args.pool
    output_pool_dir.mkdir(parents=True, exist_ok=True)

    # Copy pool TOML to output dir so the server can read display metadata
    shutil.copy2(pool_config, output_pool_dir / "config.toml")

    jobs = min(args.jobs, args.count)
    print(f"Generating {args.count} seeds for pool '{args.pool}' ({jobs} workers)")
    print(f"  Speedfog: {speedfog_path}")
    print(f"  Config: {pool_config}")
    print(f"  Game: {args.game_dir}")
    print(f"  Output: {output_pool_dir}")
    print()

    succeeded = 0
    failed = 0
    failed_dir = args.output / f"{args.pool}_failed"

    common_kwargs = dict(
        total=args.count,
        speedfog_path=speedfog_path,
        pool_config=pool_config,
        game_dir=args.game_dir,
        dll_source=dll_source,
        output_pool_dir=output_pool_dir,
        failed_dir=failed_dir,
        verbose=args.verbose,
    )

    if jobs == 1:
        for i in range(args.count):
            if generate_one_seed(index=i + 1, **common_kwargs):
                succeeded += 1
            else:
                failed += 1
    else:
        if args.verbose:
            print("Warning: --verbose output may interleave with multiple jobs")

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {
                executor.submit(generate_one_seed, index=i + 1, **common_kwargs): i
                for i in range(args.count)
            }
            for future in as_completed(futures):
                try:
                    if future.result():
                        succeeded += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    print(f"Unexpected error in seed worker: {e}")

    # Summary
    print()
    print(f"Summary: {succeeded} succeeded, {failed} failed")
    if failed > 0 and failed_dir.exists():
        print(f"Failed seeds preserved in: {failed_dir}")

    if failed > 0 and succeeded == 0:
        return 1  # total failure
    if failed > 0:
        return 2  # partial failure (some seeds generated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
