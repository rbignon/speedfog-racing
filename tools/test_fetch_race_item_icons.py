"""Tests for fetch_race_item_icons.py, served from file:// URLs.

Run: cd tools && uv run --project ../server --with pillow pytest test_fetch_race_item_icons.py
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import fetch_race_item_icons
from fetch_race_item_icons import RECIPE_KEY, fetch_icons, recipe, written_from
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


def test_writes_the_visible_art_with_a_margin_on_a_160_square(tmp_path):
    dest = tmp_path / "out"
    # A 100x200 red figure on a 300x300 transparent canvas: only the figure
    # counts. 250x250 once its 200 px span 80%: bars of 75 px left and right
    # and 25 px top and bottom, 48 px and 16 px at 160.
    art = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    art.paste((255, 0, 0, 255), (20, 60, 120, 260))
    buffer = io.BytesIO()
    art.save(buffer, format="PNG")
    url, sha256 = _served(tmp_path, "tall.png", buffer.getvalue())

    assert fetch_icons(dest, {"banana": (url, sha256)}) == (1, [])

    with Image.open(dest / "banana.png") as icon:
        assert icon.size == (160, 160)
        assert icon.info[RECIPE_KEY] == recipe(sha256)
        rgba = icon.convert("RGBA")
        assert rgba.getpixel((44, 80))[3] == 0
        assert rgba.getpixel((115, 80))[3] == 0
        assert rgba.getpixel((80, 12))[3] == 0
        assert rgba.getpixel((80, 147))[3] == 0
        assert rgba.getpixel((52, 20)) == (255, 0, 0, 255)
        assert rgba.getpixel((80, 80)) == (255, 0, 0, 255)


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
    assert written_from(dest / "banana.png") == recipe(sha256)


def test_an_icon_written_another_way_is_written_again(tmp_path, monkeypatch):
    dest = tmp_path / "out"
    sources = {"banana": _served(tmp_path, "banana.png", _png(200, 200))}
    assert fetch_icons(dest, sources) == (1, [])

    monkeypatch.setattr(fetch_race_item_icons, "CONTENT_FILL", 0.9)
    assert fetch_icons(dest, sources) == (1, [])


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
    assert written_from(dest / "shield.png") == recipe(sources["shield"][1])
    assert not list(dest.glob("*.part"))


def test_main_fails_the_build_step_on_any_failure(tmp_path, monkeypatch, capsys):
    sources = {"banana": ((tmp_path / "gone.png").as_uri(), "0" * 64)}
    monkeypatch.setattr(fetch_race_item_icons, "ICON_SOURCES", sources)

    assert fetch_race_item_icons.main(["--dest", str(tmp_path / "out")]) == 1
    assert "banana: cannot download" in capsys.readouterr().err
