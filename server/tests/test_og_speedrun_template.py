"""Render-time validation for the speedrun.fog OG SVG templates."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from speedfog_racing.services.og_image import render_svg

_AVATAR = "data:image/png;base64,iVBORw0KGgo="


def _record(**overrides: object) -> dict:
    base = {
        "name": "Abisxoxo",
        "name_size": 48,
        "avatar_b64": _AVATAR,
        "kind": "Replay",
        "day": "5 November 2026",
        "time": "23m 43s",
    }
    base.update(overrides)
    return base


def _board_ctx(**overrides: object) -> dict:
    base = {
        "accent_color": "#c8a44e",
        "status_label": "Speedrun",
        "sub_label": "SET SEED",
        "category": "Standard",
        "category_size": 84,
        "record": _record(),
        "players_label": "207 players",
        "seed_number": "69628472728a",
    }
    base.update(overrides)
    return base


def _seed_ctx(**overrides: object) -> dict:
    base = {
        "accent_color": "#c8a44e",
        "status_label": "Speedrun",
        "category": "Standard",
        "seed_number": "69628472728a",
        "record": _record(),
        "empty_label": "No finished run yet",
        "counts_label": "8 runs · 1 player",
        "status": "Replayable",
        "status_color": "#4aae8c",
    }
    base.update(overrides)
    return base


def test_board_template_renders_valid_svg_with_the_record() -> None:
    svg = render_svg("speedrun_board", _board_ctx())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    for text in ("SPEEDRUN", "SET SEED", "STANDARD", "WORLD RECORD", "Abisxoxo", "23m 43s"):
        assert text in svg
    assert "Replay · 5 November 2026" in svg
    assert "207 players" in svg
    assert "69628472728a" in svg


def test_board_template_without_record_says_so() -> None:
    svg = render_svg(
        "speedrun_board", _board_ctx(record=None, seed_number=None, players_label="0 players")
    )
    ET.fromstring(svg)
    assert "No run yet" in svg
    assert "WORLD RECORD" not in svg
    assert "seed <tspan" not in svg


def test_seed_template_renders_valid_svg_with_the_record() -> None:
    svg = render_svg("speedrun_seed", _seed_ctx())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    for text in ("SPEEDRUN", "STANDARD", "69628472728a", "RECORD", "Abisxoxo", "23m 43s"):
        assert text in svg
    assert "8 runs · 1 player" in svg
    assert "Replayable" in svg


def test_seed_template_without_record_shows_the_empty_label() -> None:
    svg = render_svg(
        "speedrun_seed",
        _seed_ctx(
            record=None,
            empty_label="No ranked run yet",
            status="Not replayable",
            status_color="#96a0ad",
        ),
    )
    ET.fromstring(svg)
    assert "No ranked run yet" in svg
    assert "RECORD" not in svg
    assert "Not replayable" in svg
