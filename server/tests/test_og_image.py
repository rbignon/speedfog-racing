"""Tests for the OG image rasterization pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace

from speedfog_racing.services.og_image import build_context, rasterize_svg, render_race_og

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_rasterize_returns_png_bytes() -> None:
    svg = (
        '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
        'width="120" height="63"><rect width="120" height="63" fill="#0f1923"/></svg>'
    )
    png = rasterize_svg(svg)
    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 100


def _user(name: str = "alice") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        twitch_username=name,
        twitch_display_name=name.capitalize(),
        twitch_avatar_url=f"https://cdn/{name}.png",
    )


def _participant(
    user: SimpleNamespace, *, finished: bool = False, igt_ms: int = 0
) -> SimpleNamespace:
    from speedfog_racing.models import ParticipantStatus

    return SimpleNamespace(
        user=user,
        user_id=user.id,
        status=ParticipantStatus.FINISHED if finished else ParticipantStatus.REGISTERED,
        igt_ms=igt_ms,
    )


def _race(
    *,
    status: str,
    participants: list,
    scheduled_at: dt.datetime | None = None,
    max_participants: int | None = None,
) -> SimpleNamespace:
    from speedfog_racing.models import RaceStatus

    organizer = _user("organizer")
    seed = SimpleNamespace(
        pool_name="linear_route",
        pool=SimpleNamespace(name="linear_route", config={"name": "Linear Route"}),
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Friday Night Fog",
        status=RaceStatus(status),
        organizer=organizer,
        organizer_id=organizer.id,
        participants=participants,
        seed=seed,
        scheduled_at=scheduled_at,
        max_participants=max_participants,
    )


async def test_build_context_setup_no_participants() -> None:
    race = _race(
        status="setup",
        participants=[],
        max_participants=20,
        scheduled_at=dt.datetime(2026, 4, 25, 21, 0, tzinfo=dt.UTC),
    )
    ctx = await build_context(race, avatar_lookup=lambda url: b"DEFAULT")
    assert ctx["status_label"] == "Upcoming"
    assert ctx["participant_count_label"] == "0/20 players"
    assert ctx["pool_name"] == "Linear Route"
    assert ctx["participants"] == []
    assert ctx["scheduled_label"] is not None


async def test_build_context_finished_picks_winner_by_lowest_igt() -> None:
    a, b, c = _user("a"), _user("b"), _user("c")
    parts = [
        _participant(a, finished=True, igt_ms=3000),
        _participant(b, finished=True, igt_ms=1500),
        _participant(c, finished=True, igt_ms=2500),
    ]
    race = _race(status="finished", participants=parts)
    ctx = await build_context(race, avatar_lookup=lambda url: b"AVATAR")
    assert ctx["status_label"] == "Finished"
    assert ctx["winner"]["name"] == "B"


async def test_render_race_og_writes_cache_file(tmp_path: Path) -> None:
    race = _race(status="setup", participants=[], max_participants=20)
    out_dir = tmp_path / "og"
    png, cache_key = await render_race_og(
        race, cache_dir=out_dir, avatar_lookup=lambda url: b"AVATAR"
    )
    assert png.startswith(_PNG_MAGIC)
    cached = list(out_dir.iterdir())
    assert len(cached) == 1
    assert cache_key in cached[0].name
    assert cached[0].read_bytes() == png


async def test_render_race_og_uses_cache_on_second_call(tmp_path: Path) -> None:
    race = _race(status="setup", participants=[], max_participants=20)
    out_dir = tmp_path / "og"
    calls = {"n": 0}

    def lookup(url: str | None) -> bytes:
        calls["n"] += 1
        return b"AVATAR"

    await render_race_og(race, cache_dir=out_dir, avatar_lookup=lookup)
    first_calls = calls["n"]
    await render_race_og(race, cache_dir=out_dir, avatar_lookup=lookup)
    assert calls["n"] == first_calls  # avatar lookup not re-invoked on cache hit
