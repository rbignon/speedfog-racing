"""Tests for the speedrun.fog OG cards: time wording, contexts and rasterization."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from speedfog_racing.schemas import UserResponse
from speedfog_racing.services.og_image import (
    _TEMPLATE_VERSION,
    SpeedrunBoardCard,
    SpeedrunSeedCard,
    build_speedrun_board_context,
    build_speedrun_seed_context,
    format_speedrun_time,
    render_speedrun_board_og,
    render_speedrun_seed_og,
    speedrun_board_description,
    speedrun_seed_description,
)
from speedfog_racing.services.speedrun_service import CountedRun

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# A 1x1 PNG: enough for resvg to decode the avatar.
_AVATAR = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8ffff3f0005fe02fe0d0a5d9b0000000049454e44ae426082"
)


def _avatar(url: str | None) -> bytes:
    return _AVATAR


def _run(
    *,
    name: str = "Abisxoxo",
    igt_ms: int = 1423772,
    blind: bool = False,
    finished_at: datetime = datetime(2026, 11, 5, 14, 44, tzinfo=UTC),
    seed_number: str = "69628472728a",
) -> CountedRun:
    user = UserResponse(
        id=uuid.uuid4(),
        twitch_username=name.lower(),
        twitch_display_name=name,
        twitch_avatar_url=None,
    )
    return CountedRun(
        run_id=uuid.uuid4(),
        user=user,
        pool="standard",
        category="standard",
        deathless=False,
        run_type="solo" if not blind else "race",
        blind=blind,
        igt_ms=igt_ms,
        finished_at=finished_at,
        race_id=None,
        race_name=None,
        session_id=uuid.uuid4(),
        daily_date=None,
        seed_number=seed_number,
        deaths=1,
        seed_excluded=False,
        seed_files_block=None,
    )


def _board(**overrides: object) -> SpeedrunBoardCard:
    fields: dict = {
        "category_name": "Standard",
        "sub": "set",
        "deathless": False,
        "record": _run(),
        "players": 207,
    }
    fields.update(overrides)
    return SpeedrunBoardCard(**fields)


def _seed(**overrides: object) -> SpeedrunSeedCard:
    fields: dict = {
        "seed_number": "69628472728a",
        "category_name": "Standard",
        "record": _run(),
        "runs": 8,
        "players": 1,
        "replayable": True,
    }
    fields.update(overrides)
    return SpeedrunSeedCard(**fields)


@pytest.mark.parametrize(
    "ms,expected",
    [
        (1423772, "23m 43s"),
        (3750000, "1h 02m 30s"),
        (3600000, "1h 00m 00s"),
        (59999, "0m 59s"),
        (5000, "0m 05s"),
        (0, "0m 00s"),
    ],
)
def test_format_speedrun_time_matches_the_boards(ms: int, expected: str) -> None:
    """speedrun.com style, as the web's ``speedrunTimeParts``: minutes unpadded,
    seconds padded, hours only when there are some (then minutes padded)."""
    assert format_speedrun_time(ms) == expected


async def test_board_context_names_the_sub_and_the_record() -> None:
    ctx = await build_speedrun_board_context(_board(), avatar_lookup=_avatar)

    assert ctx["sub_label"] == "SET SEED"
    assert ctx["category"] == "Standard"
    assert ctx["players_label"] == "207 players"
    assert ctx["seed_number"] == "69628472728a"
    record = ctx["record"]
    assert record["name"] == "Abisxoxo"
    assert record["kind"] == "Replay"
    assert record["day"] == "5 November 2026"
    assert record["time"] == "23m 43s"
    assert record["avatar_b64"].startswith("data:image/png;base64,")


async def test_board_context_marks_random_seed_deathless_and_blind() -> None:
    card = _board(sub="random", deathless=True, record=_run(blind=True), players=1)
    ctx = await build_speedrun_board_context(card, avatar_lookup=_avatar)

    assert ctx["sub_label"] == "RANDOM SEED · DEATHLESS"
    assert ctx["record"]["kind"] == "Blind"
    assert ctx["players_label"] == "1 player"


async def test_board_context_without_record_has_no_holder() -> None:
    ctx = await build_speedrun_board_context(_board(record=None, players=0), avatar_lookup=_avatar)

    assert ctx["record"] is None
    assert ctx["seed_number"] is None
    assert ctx["players_label"] == "0 players"


async def test_board_context_shrinks_a_long_name_beside_a_long_time() -> None:
    """The holder's name and the time share one line: a long name next to an
    hours-long time steps down so the two never overlap."""
    short = await build_speedrun_board_context(_board(), avatar_lookup=_avatar)
    long = await build_speedrun_board_context(
        _board(record=_run(name="x" * 25, igt_ms=3750000)), avatar_lookup=_avatar
    )

    assert short["record"]["name_size"] == 48
    assert long["record"]["name_size"] < short["record"]["name_size"]


async def test_seed_context_counts_and_status() -> None:
    ctx = await build_speedrun_seed_context(_seed(), avatar_lookup=_avatar)

    assert ctx["category"] == "Standard"
    assert ctx["seed_number"] == "69628472728a"
    assert ctx["counts_label"] == "8 runs · 1 player"
    assert ctx["status"] == "Replayable"
    assert ctx["record"]["time"] == "23m 43s"


async def test_seed_context_without_finished_run() -> None:
    ctx = await build_speedrun_seed_context(
        _seed(record=None, runs=0, players=0, replayable=False), avatar_lookup=_avatar
    )

    assert ctx["record"] is None
    assert ctx["empty_label"] == "No finished run yet"
    assert ctx["counts_label"] == "0 runs · 0 players"
    assert ctx["status"] == "Not replayable"


async def test_seed_context_with_unranked_runs_only() -> None:
    """A seed whose runs all count on no board (a seen seed, a reset race)
    lists them on its page: the card must not deny them."""
    ctx = await build_speedrun_seed_context(
        _seed(record=None, runs=3, players=2), avatar_lookup=_avatar
    )

    assert ctx["record"] is None
    assert ctx["empty_label"] == "No ranked run yet"
    assert ctx["counts_label"] == "3 runs · 2 players"


async def test_record_day_reads_a_naive_finish_as_utc(monkeypatch) -> None:
    """SQLite hands back naive datetimes: a run finished just after midnight
    UTC is dated that day whatever the host's zone."""
    import time

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        ctx = await build_speedrun_board_context(
            _board(record=_run(finished_at=datetime(2026, 11, 5, 0, 30))), avatar_lookup=_avatar
        )
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()

    assert ctx["record"]["day"] == "5 November 2026"


def test_board_description_reads_like_the_wr_band() -> None:
    assert speedrun_board_description(_board()) == (
        "World record 23m 43s by Abisxoxo · Replay, 5 November 2026 · 207 players"
    )
    assert speedrun_board_description(_board(record=None, players=0)) == "No run yet"


def test_seed_description_reads_the_record_and_the_status() -> None:
    assert speedrun_seed_description(_seed()) == (
        "Record 23m 43s by Abisxoxo · Replay, 5 November 2026 · 8 runs · 1 player · Replayable"
    )
    assert speedrun_seed_description(_seed(record=None, runs=0, players=0)) == (
        "No finished run yet · 0 runs · 0 players · Replayable"
    )
    assert speedrun_seed_description(_seed(record=None, runs=3, players=2)) == (
        "No ranked run yet · 3 runs · 2 players · Replayable"
    )


async def test_render_board_writes_png_keyed_by_what_it_shows(tmp_path: Path) -> None:
    out_dir = tmp_path / "og"
    card = _board()
    png = await render_speedrun_board_og(card, cache_dir=out_dir, avatar_lookup=_avatar)

    assert png.startswith(_PNG_MAGIC)
    files = sorted(out_dir.glob(f"speedrun-board-v{_TEMPLATE_VERSION}-*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == png

    # The same run with a better time renders to a file of its own; the same
    # card reads its file back.
    assert card.record is not None
    await render_speedrun_board_og(
        _board(record=replace(card.record, igt_ms=1400000)),
        cache_dir=out_dir,
        avatar_lookup=_avatar,
    )
    assert len(list(out_dir.glob("speedrun-board-*.png"))) == 2
    files[0].write_bytes(b"\x89PNG\r\n\x1a\nTAMPERED")
    again = await render_speedrun_board_og(card, cache_dir=out_dir, avatar_lookup=_avatar)
    assert again == b"\x89PNG\r\n\x1a\nTAMPERED"


async def test_render_seed_writes_png_named_after_the_seed(tmp_path: Path) -> None:
    out_dir = tmp_path / "og"
    png = await render_speedrun_seed_og(_seed(), cache_dir=out_dir, avatar_lookup=_avatar)

    assert png.startswith(_PNG_MAGIC)
    files = list(out_dir.glob(f"speedrun-seed-v{_TEMPLATE_VERSION}-69628472728a-*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == png
