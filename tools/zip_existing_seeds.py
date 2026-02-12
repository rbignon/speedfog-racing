#!/usr/bin/env python3
"""Convert existing seed directories to zip archives.

Scans a pool directory for seed_* directories, zips them with a
speedfog_{slug}/ top-level directory structure, and optionally deletes
the original directories.

Usage:
    python zip_existing_seeds.py /data/seeds/standard
    python zip_existing_seeds.py /data/seeds/standard --delete-originals
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert seed directories to zip archives",
    )
    parser.add_argument(
        "pool_dir",
        type=Path,
        help="Path to pool directory containing seed_* directories",
    )
    parser.add_argument(
        "--delete-originals",
        action="store_true",
        help="Delete original directories after successful zip creation",
    )
    args = parser.parse_args()

    pool_dir: Path = args.pool_dir
    if not pool_dir.exists():
        print(f"Error: {pool_dir} does not exist")
        return 1

    seed_dirs = sorted(
        d for d in pool_dir.iterdir() if d.is_dir() and d.name.startswith("seed_")
    )

    if not seed_dirs:
        print(f"No seed_* directories found in {pool_dir}")
        return 0

    print(f"Found {len(seed_dirs)} seed directories to convert")

    converted = 0
    skipped = 0

    for seed_dir in seed_dirs:
        slug = seed_dir.name.removeprefix("seed_")
        output_zip = pool_dir / f"{seed_dir.name}.zip"
        top_dir = f"speedfog_{slug}"

        if output_zip.exists():
            print(f"  Skip {seed_dir.name} (zip already exists)")
            skipped += 1
            continue

        print(f"  Zipping {seed_dir.name} -> {output_zip.name}...", end=" ", flush=True)
        try:
            zip_seed_dir(seed_dir, output_zip, top_dir)
            print(f"OK ({output_zip.stat().st_size / 1024 / 1024:.1f} MB)")
            converted += 1

            if args.delete_originals:
                shutil.rmtree(seed_dir)
                print(f"    Deleted {seed_dir.name}/")
        except Exception as e:
            print(f"FAILED: {e}")
            # Clean up partial zip
            output_zip.unlink(missing_ok=True)
            return 1

    print(f"\nDone: {converted} converted, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
