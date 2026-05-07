"""Tests for the daily OG image rasterization pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from speedfog_racing.services.og_image import render_daily_og

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _race(daily_date: dt.date = dt.date(2026, 4, 27)) -> SimpleNamespace:
    seed = SimpleNamespace(
        pool_name="hardcore",
        pool=SimpleNamespace(name="hardcore", config={"name": "Hardcore"}),
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        daily_date=daily_date,
        seed=seed,
    )


async def test_render_daily_og_writes_png_to_disk(tmp_path: Path) -> None:
    race = _race()
    out_dir = tmp_path / "og"
    png = await render_daily_og(race, cache_dir=out_dir)
    assert png.startswith(_PNG_MAGIC)
    expected = out_dir / "daily-2026-04-27.png"
    assert expected.exists()
    assert expected.read_bytes() == png


async def test_render_daily_og_reuses_cached_file(tmp_path: Path) -> None:
    """Second call must read the file rather than re-rasterize."""
    race = _race()
    out_dir = tmp_path / "og"
    first = await render_daily_og(race, cache_dir=out_dir)
    cached = out_dir / "daily-2026-04-27.png"
    # Tamper with the file: a fresh render would overwrite it; a cache hit
    # would return the tampered bytes verbatim.
    cached.write_bytes(b"\x89PNG\r\n\x1a\nTAMPERED")
    second = await render_daily_og(race, cache_dir=out_dir)
    assert second == b"\x89PNG\r\n\x1a\nTAMPERED"
    assert first != second


async def test_render_daily_og_formats_date_label_with_weekday() -> None:
    """The rendered SVG must contain the long-form date with weekday."""
    from speedfog_racing.services.og_image import _build_daily_context

    race = _race(dt.date(2026, 4, 27))  # a Monday
    ctx = _build_daily_context(race)
    assert ctx["date_label"] == "Monday 27 April 2026"
    assert ctx["pool_display_name"] == "Hardcore"


@pytest.mark.parametrize(
    "the_date,expected",
    [
        (dt.date(2026, 5, 5), "Tuesday 5 May 2026"),
        (dt.date(2026, 1, 1), "Thursday 1 January 2026"),
        (dt.date(2026, 12, 31), "Thursday 31 December 2026"),
    ],
)
def test_daily_date_label_handles_various_dates(the_date: dt.date, expected: str) -> None:
    from speedfog_racing.services.og_image import format_daily_date

    assert format_daily_date(the_date) == expected
