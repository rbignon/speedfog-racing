"""Render-time validation for the event OG SVG templates."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

import pytest

from speedfog_racing.services.og_image import render_svg

_SVG_NS = "{http://www.w3.org/2000/svg}"

_AVATAR = "data:image/png;base64,AAAA"


def _ctx(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "accent_color": "#dc6a51",
        "status_label": "Qualifier open",
        "partner_name": "Ignite",
        "event_name": "Season One",
        "logo_b64": "data:image/webp;base64,BBBB",
        "lockup_font_size": 58,
        "headline_font_size": 84,
        "winner_font_size": 72,
        "caption_gap": 76,
        "headline_label": "Qualifier opens",
        "headline": "Wednesday 23 September",
        "caption": "Qualifier closes on 30 September",
        "caption_font_size": 34,
        "stage_label": "Semi A",
        "stage_date": "Sunday 4 October",
        "entrants": [{"avatar_b64": _AVATAR} for _ in range(3)],
        "overflow_count": 0,
        "field": [
            {"name": "ana", "avatar_b64": _AVATAR, "label": "Seed 1"},
            {"name": None, "avatar_b64": None, "label": "Top 2 of Semi B"},
        ],
        "field_overflow_count": 0,
        "field_size": 96,
        "field_gap": 44,
        "winner": {"name": "wospince", "avatar_b64": _AVATAR},
        "player_count_label": "24 players",
        "window_label": "23 September - 25 October 2026",
    }
    base.update(overrides)
    return base


def _images(svg: str) -> list[ET.Element]:
    return list(ET.fromstring(svg).iter(f"{_SVG_NS}image"))


@pytest.mark.parametrize(
    "kind", ["event_upcoming", "event_entrants", "event_stage", "event_winner"]
)
def test_every_event_template_renders_valid_svg(kind: str) -> None:
    root = ET.fromstring(render_svg(kind, _ctx()))
    assert root.tag == f"{_SVG_NS}svg"


def test_the_badge_carries_the_phase_in_upper_case() -> None:
    svg = render_svg("event_entrants", _ctx(status_label="Qualifier closed"))
    assert "QUALIFIER CLOSED" in svg


def test_the_lockup_names_the_partner_and_the_event() -> None:
    svg = render_svg("event_entrants", _ctx(partner_name="Ignite", event_name="Season Two"))
    assert "IGNITE" in svg
    assert "SEASON TWO" in svg


def test_an_event_without_a_partner_drops_the_cross() -> None:
    svg = render_svg("event_entrants", _ctx(partner_name=None, logo_b64=None))
    assert "&#215;" not in svg
    assert not _images(
        render_svg("event_upcoming", _ctx(partner_name=None, logo_b64=None, entrants=[]))
    )


def test_the_lockup_draws_the_logo_when_there_is_one() -> None:
    svg = render_svg("event_upcoming", _ctx(entrants=[]))
    assert len(_images(svg)) == 1


def test_the_upcoming_card_draws_the_entrants_row_only_when_handed_one() -> None:
    bare = render_svg("event_upcoming", _ctx(entrants=[], overflow_count=0))
    assert len(_images(bare)) == 1  # the partner logo alone
    assert "WEDNESDAY 23 SEPTEMBER" in bare
    crowded = render_svg(
        "event_upcoming", _ctx(entrants=[{"avatar_b64": _AVATAR}] * 12, overflow_count=3)
    )
    assert len(_images(crowded)) == 13
    assert "+3" in crowded
    assert "WEDNESDAY 23 SEPTEMBER" in crowded


def test_entrants_render_one_avatar_each() -> None:
    svg = render_svg("event_entrants", _ctx(entrants=[{"avatar_b64": _AVATAR}] * 5))
    # Five entrants plus the partner logo.
    assert len(_images(svg)) == 6


def test_the_overflow_chip_appears_only_when_runners_are_left_out() -> None:
    assert "+7" not in render_svg("event_entrants", _ctx(overflow_count=0))
    assert "+7" in render_svg("event_entrants", _ctx(overflow_count=7))


def test_an_undecided_stage_slot_shows_its_label_without_an_avatar() -> None:
    svg = render_svg("event_stage", _ctx())
    # One decided runner plus the partner logo; the undecided slot draws no image.
    assert len(_images(svg)) == 2
    assert "Top 2 of Semi B" in svg
    assert "ana" in svg


def test_the_stage_caption_joins_the_label_and_the_date() -> None:
    svg = render_svg("event_stage", _ctx(stage_label="Semi B", stage_date="Sunday 11 October"))
    assert "SEMI B" in svg
    assert "SUNDAY 11 OCTOBER" in svg


def test_the_winner_template_names_the_winner() -> None:
    svg = render_svg("event_winner", _ctx(winner={"name": "wospince", "avatar_b64": _AVATAR}))
    assert "wospince" in svg
    assert "WINNER" in svg


def test_the_footer_drops_the_player_count_before_anyone_joins() -> None:
    svg = render_svg("event_upcoming", _ctx(player_count_label=None))
    assert "players" not in svg
    assert "23 September - 25 October 2026" in svg


def test_an_entrant_row_with_nobody_in_it_says_so() -> None:
    """A qualifier that just opened would otherwise show an empty band."""
    assert "No players yet" in render_svg("event_entrants", _ctx(entrants=[]))
    assert "No players yet" not in render_svg("event_entrants", _ctx())
