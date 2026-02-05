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
from pathlib import Path


VALID_POOLS = ["sprint", "standard", "marathon"]
SCRIPT_DIR = Path(__file__).parent.resolve()
DLL_NAME = "speedfog_race_mod.dll"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
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
        choices=VALID_POOLS,
        help="Pool name (sprint, standard, marathon)",
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


def process_seed(
    seed_dir: Path,
    dll_source: Path,
    output_pool_dir: Path,
    seed_number: int,
) -> bool:
    """Post-process a generated seed: add DLL, modify config, move to output.

    Returns True on success, False on failure.
    """
    # Copy the mod DLL
    if not copy_mod_dll(seed_dir, dll_source):
        return False

    # Modify config_speedfog.toml
    if not add_dll_to_config(seed_dir):
        return False

    # Move to final location with seed_N naming
    final_name = f"seed_{seed_number}"
    final_path = output_pool_dir / final_name

    # Remove existing if present
    if final_path.exists():
        shutil.rmtree(final_path)

    try:
        shutil.move(str(seed_dir), str(final_path))
        return True
    except OSError as e:
        print(f"  Error moving seed to output: {e}")
        return False


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Validate count
    if args.count <= 0:
        print("Error: --count must be a positive integer")
        return 1

    # Validate paths
    speedfog_path = get_speedfog_path(args)
    if not speedfog_path.exists():
        print(f"Error: Speedfog path does not exist: {speedfog_path}")
        return 1

    pool_config = SCRIPT_DIR / "pools" / args.pool / "config.toml"
    if not pool_config.exists():
        print(f"Error: Pool config not found: {pool_config}")
        return 1

    dll_source = SCRIPT_DIR / "assets" / DLL_NAME
    if not dll_source.exists():
        print(f"Error: DLL not found: {dll_source}")
        print("Download it from GitHub Actions and place it in tools/assets/")
        return 1

    if not args.game_dir.exists():
        print(f"Error: Game directory does not exist: {args.game_dir}")
        return 1

    # Create output directory
    output_pool_dir = args.output / args.pool
    output_pool_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.count} seeds for pool '{args.pool}'")
    print(f"  Speedfog: {speedfog_path}")
    print(f"  Config: {pool_config}")
    print(f"  Game: {args.game_dir}")
    print(f"  Output: {output_pool_dir}")
    print()

    # Find the next seed number (continue from existing)
    existing_seeds = []
    for d in output_pool_dir.iterdir():
        if d.is_dir() and d.name.startswith("seed_"):
            parts = d.name.split("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                existing_seeds.append(int(parts[1]))
    start_number = max(existing_seeds, default=0) + 1

    succeeded = 0
    failed = 0

    for i in range(args.count):
        seed_number = start_number + i
        print(f"[{i + 1}/{args.count}] Generating seed_{seed_number}...")

        # Use a temporary directory for speedfog output
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Generate seed
            seed_dir = run_speedfog(
                speedfog_path,
                pool_config,
                temp_path,
                args.game_dir,
                verbose=args.verbose,
            )
            if seed_dir is None:
                print("  Failed: speedfog generation error")
                failed += 1
                continue

            # Process and move to output
            if process_seed(seed_dir, dll_source, output_pool_dir, seed_number):
                print(f"  Success: {output_pool_dir / f'seed_{seed_number}'}")
                succeeded += 1
            else:
                print("  Failed: post-processing error")
                failed += 1

    # Summary
    print()
    print(f"Summary: {succeeded} succeeded, {failed} failed")

    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
