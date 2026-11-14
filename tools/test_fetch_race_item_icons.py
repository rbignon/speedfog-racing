"""Tests for fetch_race_item_icons.py, served from file:// URLs.

Run: cd tools && uv run --project ../server --with pillow pytest test_fetch_race_item_icons.py
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import fetch_race_item_icons
from fetch_race_item_icons import HASH_KEY, fetch_icons, written_from
from PIL import Image


def _png(width: int, height: int, color=(255, 0, 0, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _served(tmp_path: Path, name: str, data: bytes) -> tuple[str, str]:
    """A file:// source serving data, with its hash."""
    served = tmp_path / "site" / name
    served.parent.mkdir(exist_ok=True)
    served.write_bytes(data)
    return served.as_uri(), hashlib.sha256(data).hexdigest()


def test_writes_the_art_centered_on_a_transparent_160_square(tmp_path):
    dest = tmp_path / "out"
    url, sha256 = _served(tmp_path, "tall.png", _png(100, 200))

    assert fetch_icons(dest, {"banana": (url, sha256)}) == (1, [])

    with Image.open(dest / "banana.png") as icon:
        assert icon.size == (160, 160)
        assert icon.info[HASH_KEY] == sha256
        rgba = icon.convert("RGBA")
        # 200x200 with 50 px bars left and right, 40 px once at 160.
        assert rgba.getpixel((10, 80))[3] == 0
        assert rgba.getpixel((150, 80))[3] == 0
        assert rgba.getpixel((80, 5)) == (255, 0, 0, 255)


def test_an_icon_written_from_its_source_is_not_downloaded_again(tmp_path):
    dest = tmp_path / "out"
    sources = {"banana": _served(tmp_path, "banana.png", _png(200, 200))}
    assert fetch_icons(dest, sources) == (1, [])

    (tmp_path / "site" / "banana.png").unlink()
    assert fetch_icons(dest, sources) == (0, [])


def test_an_icon_from_another_source_is_replaced(tmp_path):
    # A former placeholder, or an icon written from an older source.
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "banana.png").write_bytes(_png(160, 160, (0, 0, 255, 255)))
    url, sha256 = _served(tmp_path, "banana.png", _png(200, 200))

    assert fetch_icons(dest, {"banana": (url, sha256)}) == (1, [])
    assert written_from(dest / "banana.png") == sha256


def test_a_failure_only_fails_its_icon_and_keeps_its_file(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    old = _png(160, 160, (0, 0, 255, 255))
    (dest / "banana.png").write_bytes(old)
    url, _ = _served(tmp_path, "banana.png", _png(200, 200))
    sources = {
        "banana": (url, hashlib.sha256(b"the pinned upload").hexdigest()),
        "hammer": ((tmp_path / "site" / "gone.png").as_uri(), "0" * 64),
        "ink": _served(tmp_path, "ink.png", b"<html>not an image</html>"),
        "shield": _served(tmp_path, "shield.png", _png(200, 200)),
    }

    downloaded, problems = fetch_icons(dest, sources)

    assert downloaded == 1
    assert [p.split(":")[0] for p in problems] == ["banana", "hammer", "ink"]
    assert "update ICON_SOURCES" in problems[0]
    assert (dest / "banana.png").read_bytes() == old
    assert not (dest / "hammer.png").exists()
    assert not (dest / "ink.png").exists()
    assert written_from(dest / "shield.png") == sources["shield"][1]
    assert not list(dest.glob("*.part"))


def test_main_fails_the_build_step_on_any_failure(tmp_path, monkeypatch, capsys):
    sources = {"banana": ((tmp_path / "gone.png").as_uri(), "0" * 64)}
    monkeypatch.setattr(fetch_race_item_icons, "ICON_SOURCES", sources)

    assert fetch_race_item_icons.main(["--dest", str(tmp_path / "out")]) == 1
    assert "banana: cannot download" in capsys.readouterr().err
