"""Render-time validation for OG SVG templates."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from speedfog_racing.services.og_image import render_svg


def _ctx(**overrides: object) -> dict:
    base = {
        "race_name": "Friday Night Fog #42",
        "status_label": "Upcoming",
        "accent_color": "#3b82f6",
        "pool_name": "Linear Route",
        "participant_count_label": "0/20 players",
        "organizer_name": "crazydiamond",
        "organizer_avatar_b64": "data:image/png;base64,AA==",
        "participants": [],
        "overflow_count": 0,
        "winner": None,
        "scheduled_label": "Today, 9:00 PM",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "status,label,accent",
    [
        ("setup", "Upcoming", "#4aae8c"),
        ("running", "Live", "#dc6a51"),
        ("finished", "Finished", "#7ba2cc"),
    ],
)
def test_each_template_renders_valid_svg(status: str, label: str, accent: str) -> None:
    svg = render_svg(status, _ctx(status_label=label, accent_color=accent))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "FRIDAY NIGHT FOG #42" in svg
    assert label.upper() in svg
    assert "Linear Route" in svg
    assert "crazydiamond" in svg
    assert accent in svg


def test_race_name_with_markup_characters_renders_valid_svg() -> None:
    """XML specials in user-supplied names must be escaped, not break the SVG."""
    svg = render_svg("running", _ctx(race_name="Fog & Friends <3", status_label="Live"))
    ET.fromstring(svg)  # raises ParseError if '&' or '<' leaked through raw
    assert "FOG &amp; FRIENDS &lt;3" in svg


def test_setup_with_no_participants_renders_no_players_yet() -> None:
    svg = render_svg("setup", _ctx())
    assert "No players yet" in svg


def test_setup_with_participants_renders_avatars() -> None:
    parts = [{"name": f"P{i}", "avatar_b64": "data:image/png;base64,AA=="} for i in range(6)]
    svg = render_svg("setup", _ctx(participants=parts, overflow_count=2))
    assert "+2" in svg
    assert "No players yet" not in svg


def test_running_template_does_not_include_per_racer_times() -> None:
    import re

    parts = [{"name": "Alice", "avatar_b64": "data:image/png;base64,AA=="}]
    svg = render_svg("running", _ctx(status_label="Live", participants=parts))
    # Sanity: no IGT-formatted times like "MM:SS" (guards against
    # accidental leaderboard reintroduction)
    assert not re.search(r"\b\d{1,2}:\d{2}\b", svg)


def test_finished_template_renders_winner() -> None:
    # Distinct from organizer_name so the assertion fails if the
    # `{% if winner %}` block is broken or the organizer is rendered
    # in its place.
    winner = {"name": "WinnerBob", "avatar_b64": "data:image/png;base64,AA=="}
    svg = render_svg("finished", _ctx(status_label="Finished", winner=winner))
    assert "WinnerBob" in svg
