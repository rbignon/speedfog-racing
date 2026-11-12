"""Tests for sync_race_item_icons.py: validation is all-or-nothing."""

from __future__ import annotations

import struct
import zlib

import sync_race_item_icons


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _speedfog(tmp_path, icons=("shield", "banana")):
    plugins = tmp_path / "speedfog" / "data" / "plugins"
    plugins.mkdir(parents=True)
    names = "\n".join(f"{name} = {60385 + i}" for i, name in enumerate(icons))
    (plugins / "race_items.toml").write_text(f"[icons]\n{names}\n")
    return tmp_path / "speedfog", plugins


def test_copies_every_icon_listed_in_the_catalog(tmp_path):
    sf, plugins = _speedfog(tmp_path)
    for name in ("shield", "banana"):
        (plugins / f"race_items_icon_{name}.png").write_bytes(_png(160, 160))
    dest = tmp_path / "out"
    assert (
        sync_race_item_icons.main(["--speedfog-dir", str(sf), "--dest", str(dest)]) == 0
    )
    for name in ("shield", "banana"):
        assert (dest / f"{name}.png").read_bytes() == (
            plugins / f"race_items_icon_{name}.png"
        ).read_bytes()


def test_refuses_a_wrong_size_and_copies_nothing(tmp_path, capsys):
    sf, plugins = _speedfog(tmp_path)
    (plugins / "race_items_icon_shield.png").write_bytes(_png(160, 160))
    (plugins / "race_items_icon_banana.png").write_bytes(_png(128, 128))
    dest = tmp_path / "out"
    assert (
        sync_race_item_icons.main(["--speedfog-dir", str(sf), "--dest", str(dest)]) != 0
    )
    assert "race_items_icon_banana.png" in capsys.readouterr().err
    assert not dest.exists() or not list(dest.iterdir())


def test_refuses_a_missing_icon(tmp_path, capsys):
    sf, plugins = _speedfog(tmp_path)
    (plugins / "race_items_icon_shield.png").write_bytes(_png(160, 160))
    dest = tmp_path / "out"
    assert (
        sync_race_item_icons.main(["--speedfog-dir", str(sf), "--dest", str(dest)]) != 0
    )
    assert "race_items_icon_banana.png" in capsys.readouterr().err
    assert not dest.exists() or not list(dest.iterdir())


def test_refuses_a_file_that_is_not_a_png(tmp_path, capsys):
    sf, plugins = _speedfog(tmp_path, icons=("shield",))
    (plugins / "race_items_icon_shield.png").write_bytes(b"GIF89a" + b"\x00" * 40)
    dest = tmp_path / "out"
    assert (
        sync_race_item_icons.main(["--speedfog-dir", str(sf), "--dest", str(dest)]) != 0
    )
    assert "race_items_icon_shield.png" in capsys.readouterr().err
