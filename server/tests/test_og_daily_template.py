"""Render-time validation for the daily OG SVG template."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from speedfog_racing.services.og_image import render_svg


def _ctx(**overrides: object) -> dict:
    base = {
        "accent_color": "#c8a44e",
        "date_label": "Monday 27 April 2026",
        "pool_display_name": "Hardcore",
    }
    base.update(overrides)
    return base


def test_daily_template_renders_valid_svg() -> None:
    svg = render_svg("daily", _ctx())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_daily_template_renders_dynamic_fields() -> None:
    svg = render_svg(
        "daily",
        _ctx(date_label="Tuesday 5 May 2026", pool_display_name="Linear Route"),
    )
    assert "Tuesday 5 May 2026" in svg
    assert "Linear Route" in svg


def test_daily_template_does_not_render_status_badge() -> None:
    """Daily has no status concept; the badge block must be empty."""
    svg = render_svg("daily", _ctx())
    # The default badge rendering would emit one of these labels in upper case.
    for label in ("UPCOMING", "LIVE", "FINISHED"):
        assert label not in svg
