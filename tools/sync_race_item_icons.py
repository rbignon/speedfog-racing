#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Copy the race item icons from the speedfog repo into the mod's assets.

The icon names come from the `[icons]` table of speedfog's
data/plugins/race_items.toml; each one must exist as
data/plugins/race_items_icon_<icon>.png, be a PNG and be a square of at least
160x160 (the art is delivered at 1024x1024). Every file is checked first: any
problem lists all the bad files and nothing is copied. Each icon is written at
160x160, downscaled when larger: the banner draws it at 7.5% of the screen
width (144 px at 1080p), and the full-size art would weigh megabytes in the
DLL. The final art lands by replacing the PNGs in speedfog, running this tool
and releasing the mod. `unknown.png` (the fallback icon) is not in the catalog
and is never touched.

Usage: uv run tools/sync_race_item_icons.py [--speedfog-dir DIR] [--dest DIR]
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
import tomllib
from pathlib import Path

from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MOD_SIZE = 160
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEEDFOG = REPO_ROOT.parent / "speedfog"
DEFAULT_DEST = REPO_ROOT / "mod" / "assets" / "race_items"


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from the IHDR chunk, or None when not a PNG."""
    if len(data) < 24 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def check_icon(path: Path) -> str | None:
    """A problem description for one icon file, or None when it is fine."""
    if not path.is_file():
        return "missing"
    size = png_size(path.read_bytes())
    if size is None:
        return "not a PNG"
    width, height = size
    if width != height or width < MOD_SIZE:
        return (
            f"is {width}x{height}, expected a square of at least {MOD_SIZE}x{MOD_SIZE}"
        )
    return None


def write_icon(source: Path, dest: Path) -> None:
    """Copy one icon, downscaled to MOD_SIZE x MOD_SIZE when larger."""
    with Image.open(source) as image:
        if image.size == (MOD_SIZE, MOD_SIZE):
            shutil.copyfile(source, dest)
            return
        resized = image.convert("RGBA").resize(
            (MOD_SIZE, MOD_SIZE), Image.Resampling.BICUBIC
        )
    resized.save(dest, optimize=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--speedfog-dir", type=Path, default=DEFAULT_SPEEDFOG)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)

    plugins = args.speedfog_dir / "data" / "plugins"
    catalog = plugins / "race_items.toml"
    try:
        with catalog.open("rb") as handle:
            names = list(tomllib.load(handle).get("icons", {}))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"cannot read {catalog}: {exc}", file=sys.stderr)
        return 1
    if not names:
        print(f"{catalog} lists no icons", file=sys.stderr)
        return 1

    sources = {name: plugins / f"race_items_icon_{name}.png" for name in names}
    problems = [
        f"{path.name}: {problem}"
        for path in sources.values()
        if (problem := check_icon(path))
    ]
    if problems:
        print("nothing copied:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    args.dest.mkdir(parents=True, exist_ok=True)
    for name, path in sources.items():
        write_icon(path, args.dest / f"{name}.png")
    print(f"copied {len(sources)} icons to {args.dest} at {MOD_SIZE}x{MOD_SIZE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
