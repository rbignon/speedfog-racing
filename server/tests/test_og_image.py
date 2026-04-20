"""Tests for the OG image rasterization pipeline."""

from __future__ import annotations

from speedfog_racing.services.og_image import rasterize_svg

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_rasterize_returns_png_bytes() -> None:
    svg = (
        '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
        'width="120" height="63"><rect width="120" height="63" fill="#0f1923"/></svg>'
    )
    png = rasterize_svg(svg)
    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 100
