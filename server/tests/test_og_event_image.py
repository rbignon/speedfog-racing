"""Tests for the event OG summary and rasterization pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace

from speedfog_racing.models import ParticipantStatus, RaceStatus
from speedfog_racing.services.og_image import (
    _TEMPLATE_VERSION,
    build_event_context,
    render_event_og,
    render_svg,
    summarize_event,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

STARTS = dt.datetime(2026, 9, 23, 8, tzinfo=dt.UTC)  # a Wednesday
CUT = dt.datetime(2026, 9, 30, 22, tzinfo=dt.UTC)
ENDS = dt.datetime(2026, 10, 26, tzinfo=dt.UTC)

SEMI_A = dt.datetime(2026, 10, 4, 19, tzinfo=dt.UTC)  # a Sunday
SEMI_B = dt.datetime(2026, 10, 11, 19, tzinfo=dt.UTC)
NEWCOMERS = dt.datetime(2026, 10, 18, 19, tzinfo=dt.UTC)
FINAL = dt.datetime(2026, 10, 25, 19, tzinfo=dt.UTC)

CONFIG = {
    "modes": [
        {"key": "standard", "label": "Standard"},
        {"key": "boss_rush", "label": "Boss Rush"},
    ],
    "seeds_per_mode": 1,
    "stages": [
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": SEMI_A.isoformat(),
            "races": 1,
            "seeds": [1, 2],
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": SEMI_B.isoformat(),
            "races": 1,
            "seeds": [3, 4],
        },
        {
            "key": "newcomers",
            "label": "Newcomers' final",
            "kind": "newcomers",
            "date": NEWCOMERS.isoformat(),
            "races": 1,
            "size": 2,
        },
        {
            "key": "final",
            "label": "Open final",
            "kind": "final",
            "date": FINAL.isoformat(),
            "races": 1,
            "from": ["semi_a", "semi_b"],
            "advance": 2,
        },
    ],
}


def _user(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        twitch_username=name,
        twitch_display_name=name.capitalize(),
        twitch_avatar_url=f"https://cdn/{name}.png",
    )


def _entry(user: SimpleNamespace, igt_ms: int, *, started: bool = True) -> SimpleNamespace:
    history = [{"node_id": "a"}, {"node_id": "b"}] if started else []
    return SimpleNamespace(
        id=uuid.uuid4(),
        user=user,
        user_id=user.id,
        status=ParticipantStatus.FINISHED if started else ParticipantStatus.REGISTERED,
        igt_ms=igt_ms,
        current_layer=4,
        zone_history=history,
    )


def _signup(user: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(user=user, user_id=user.id)


def _race(slot: str, participants: list[SimpleNamespace], *, finished: bool = True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=slot,
        event_slot=slot,
        status=RaceStatus.FINISHED if finished else RaceStatus.RUNNING,
        participants=participants,
    )


def _event(races: list[SimpleNamespace], **overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "slug": "season-one",
        "name": "Season One",
        "partner_name": "Ignite",
        "partner_logo_url": "https://speedfog.racing/events/ignite_logo.webp",
        "starts_at": STARTS,
        "qualifier_ends_at": CUT,
        "ends_at": ENDS,
        "newcomer_threshold": 5,
        "config": CONFIG,
        "races": races,
        "signups": [],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _qualifier_world(names: list[str]) -> tuple[SimpleNamespace, dict[str, SimpleNamespace]]:
    """One seed per mode; every runner scores both, best time first in the ladder."""
    users = {name: _user(name) for name in names}
    standard = _race(
        "qualifier:standard:1",
        [_entry(u, 1_000_000 + i * 100_000) for i, u in enumerate(users.values())],
    )
    boss = _race(
        "qualifier:boss_rush:1",
        [_entry(u, 900_000 + i * 100_000) for i, u in enumerate(users.values())],
    )
    return _event([standard, boss]), users


async def _lookup(url: str | None) -> bytes:
    return b"avatar-bytes-for-" + (url or "none").encode()


async def _no_logo(url: str | None) -> bytes:
    return b""


def test_upcoming_leads_with_the_day_the_seeds_open() -> None:
    summary = summarize_event(_event([]), now=STARTS - dt.timedelta(days=3), finished_before={})
    assert summary.kind == "event_upcoming"
    assert summary.headline == "Wednesday 23 September"
    assert summary.player_count_label is None


def test_qualifier_caption_names_the_closing_day() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert summary.kind == "event_entrants"
    assert summary.caption == "Qualifier closes on 30 September"
    assert summary.player_count_label == "2 players"


def test_a_lone_entrant_is_counted_in_the_singular() -> None:
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert summary.player_count_label == "1 player"


def test_entrants_lead_with_the_ladder_order() -> None:
    event, users = _qualifier_world(["ana", "bob", "cleo"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    # Every runner scored both modes; ana has the best times, so she leads.
    assert [u.twitch_username for u in summary.entrants] == ["ana", "bob", "cleo"]
    assert summary.overflow_count == 0


def test_entrants_beyond_the_cap_become_an_overflow_count() -> None:
    event, _ = _qualifier_world([f"runner{i:02d}" for i in range(18)])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert len(summary.entrants) == 14
    assert summary.overflow_count == 4


def test_a_runner_who_never_scored_still_counts_as_a_player() -> None:
    ana, bob = _user("ana"), _user("bob")
    race = _race(
        "qualifier:standard:1",
        [_entry(ana, 1_000_000), _entry(bob, 0, started=False)],
    )
    summary = summarize_event(_event([race]), now=STARTS + dt.timedelta(days=2), finished_before={})
    assert summary.player_count_label == "2 players"
    assert [u.twitch_username for u in summary.entrants] == ["ana", "bob"]


def test_an_upcoming_event_shows_its_entrants_from_ten_players_on() -> None:
    before_opening = STARTS - dt.timedelta(days=3)
    bare = summarize_event(_event([]), now=before_opening, finished_before={})
    event = _event([], signups=[_signup(_user(f"runner{i:02d}")) for i in range(9)])
    below = summarize_event(event, now=before_opening, finished_before={})
    assert below.kind == "event_upcoming"
    assert below.entrants == []
    assert below.player_count_label is None
    assert below.cache_key == bare.cache_key
    event.signups.append(_signup(_user("runner09")))
    at = summarize_event(event, now=before_opening, finished_before={})
    assert at.kind == "event_upcoming"
    assert at.headline == "Wednesday 23 September"
    assert len(at.entrants) == 10
    assert at.player_count_label == "10 players"
    assert at.cache_key != bare.cache_key


def test_signups_join_the_qualifier_row_after_the_scored_runners() -> None:
    event, users = _qualifier_world(["ana", "bob"])
    event.signups = [_signup(_user("zed")), _signup(users["ana"]), _signup(_user("cleo"))]
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert [u.twitch_username for u in summary.entrants] == ["ana", "bob", "zed", "cleo"]
    assert summary.player_count_label == "4 players"


def test_signups_leave_the_card_at_the_cut() -> None:
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dan"])
    event.signups = [_signup(_user("zed"))]
    summary = summarize_event(event, now=CUT + dt.timedelta(hours=1), finished_before={})
    assert "zed" not in [u.twitch_username for u in summary.entrants]
    assert summary.player_count_label == "4 players"


def test_the_cut_shows_the_first_stage_still_to_come() -> None:
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    summary = summarize_event(event, now=CUT + dt.timedelta(days=1), finished_before={})
    assert summary.kind == "event_stage"
    assert summary.stage_label == "Semi A"
    assert summary.stage_date == "Sunday 4 October"


def test_the_cut_seats_the_top_of_the_ladder_in_the_first_semi() -> None:
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    summary = summarize_event(event, now=CUT + dt.timedelta(days=1), finished_before={})
    # Semi A holds seeds 1 and 2, which are the two best ladder positions.
    assert [slot.user.twitch_username for slot in summary.field] == ["ana", "bob"]


def test_playoffs_show_the_stage_of_the_day() -> None:
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    summary = summarize_event(event, now=SEMI_B + dt.timedelta(hours=1), finished_before={})
    assert summary.kind == "event_stage"
    assert summary.stage_label == "Semi B"


def test_an_undecided_final_slot_names_the_stage_it_waits_on() -> None:
    """The page says "Top 2 of Semi A"; under an empty ring only the stage fits."""
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    summary = summarize_event(event, now=FINAL - dt.timedelta(hours=2), finished_before={})
    assert summary.stage_label == "Open final"
    assert [slot.user for slot in summary.field] == [None, None, None, None]
    assert [slot.label for slot in summary.field] == ["Semi A"] * 2 + ["Semi B"] * 2


def test_a_finished_event_crowns_the_winner_of_the_final() -> None:
    event, users = _qualifier_world(["ana", "bob"])
    final = _race("final:1", [_entry(users["bob"], 800_000), _entry(users["ana"], 900_000)])
    event.races.append(final)
    summary = summarize_event(event, now=ENDS + dt.timedelta(days=1), finished_before={})
    assert summary.kind == "event_winner"
    assert summary.winner is not None
    assert summary.winner.twitch_username == "bob"


def test_a_finished_event_without_a_final_falls_back_to_the_field() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    summary = summarize_event(event, now=ENDS + dt.timedelta(days=1), finished_before={})
    assert summary.kind == "event_entrants"
    assert summary.caption == "Event finished"


def test_the_window_label_keeps_both_years_across_new_year() -> None:
    event, _ = _qualifier_world(["ana"])
    event.ends_at = dt.datetime(2027, 1, 5, tzinfo=dt.UTC)
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=1), finished_before={})
    assert summary.window_label == "23 September 2026 - 5 January 2027"


def test_the_window_label_names_the_year_once_within_one_year() -> None:
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=1), finished_before={})
    assert summary.window_label == "23 September - 26 October 2026"


def test_a_long_stage_label_shrinks_the_caption_rather_than_overflowing() -> None:
    event, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    event.config = {
        **CONFIG,
        "stages": [
            {**CONFIG["stages"][0], "label": "Semi A of the Ignite Invitational"},
            *CONFIG["stages"][1:],
        ],
    }
    summary = summarize_event(event, now=CUT + dt.timedelta(days=1), finished_before={})
    assert summary.caption_font_size < 34


def test_the_cache_key_moves_when_a_runner_joins() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    before = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    event.races[0].participants.append(_entry(_user("cleo"), 1_400_000))
    after = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert before.cache_key != after.cache_key


def test_the_cache_key_holds_still_when_nothing_moves() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    first = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    later = summarize_event(event, now=STARTS + dt.timedelta(days=3), finished_before={})
    assert first.cache_key == later.cache_key


async def test_the_context_carries_the_logo_with_its_own_image_format() -> None:
    """resvg trusts the declared data-URI type, so a webp logo must not claim PNG."""
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})

    async def webp_logo(url: str | None) -> bytes:
        return b"RIFF\x00\x00\x00\x00WEBPVP8L-not-a-real-image"

    ctx = await build_event_context(summary, avatar_lookup=_lookup, logo_lookup=webp_logo)
    assert ctx["logo_b64"].startswith("data:image/webp;base64,")


async def test_the_context_drops_the_logo_when_the_fetch_comes_back_empty() -> None:
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    ctx = await build_event_context(summary, avatar_lookup=_lookup, logo_lookup=_no_logo)
    assert ctx["logo_b64"] is None


async def test_render_event_og_writes_a_png_named_after_the_cache_key(tmp_path: Path) -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    now = STARTS + dt.timedelta(days=2)
    summary = summarize_event(event, now=now, finished_before={})
    png = await render_event_og(
        event,
        now=now,
        finished_before={},
        cache_dir=tmp_path,
        avatar_lookup=_lookup,
        logo_lookup=_no_logo,
    )
    assert png.startswith(_PNG_MAGIC)
    cached = tmp_path / f"event-season-one-v{_TEMPLATE_VERSION}-{summary.cache_key}.png"
    assert cached.read_bytes() == png


async def test_render_event_og_serves_the_cached_file_on_the_second_call(tmp_path: Path) -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    now = STARTS + dt.timedelta(days=2)
    kwargs = {
        "now": now,
        "finished_before": {},
        "cache_dir": tmp_path,
        "avatar_lookup": _lookup,
        "logo_lookup": _no_logo,
    }
    first = await render_event_og(event, **kwargs)
    cached = next(tmp_path.glob("event-season-one-*.png"))
    # Tamper with the file: a fresh render would overwrite it, a cache hit
    # returns the tampered bytes verbatim.
    cached.write_bytes(_PNG_MAGIC + b"TAMPERED")
    second = await render_event_og(event, **kwargs)
    assert second == _PNG_MAGIC + b"TAMPERED"
    assert first != second


async def test_the_context_carries_an_svg_logo_as_svg() -> None:
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})

    async def svg_logo(url: str | None) -> bytes:
        return b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'

    ctx = await build_event_context(summary, avatar_lookup=_lookup, logo_lookup=svg_logo)
    assert ctx["logo_b64"].startswith("data:image/svg+xml;base64,")


async def test_the_context_drops_a_logo_whose_bytes_are_not_an_image() -> None:
    """A site-relative URL that 404s hands the SPA's HTML back with status 200."""
    event, _ = _qualifier_world(["ana"])
    summary = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})

    async def spa_fallback(url: str | None) -> bytes:
        return b"<!doctype html><html><body>not found</body></html>"

    ctx = await build_event_context(summary, avatar_lookup=_lookup, logo_lookup=spa_fallback)
    assert ctx["logo_b64"] is None


def test_the_cache_key_moves_when_the_partner_logo_does() -> None:
    """The logo is drawn on the card and it narrows the lockup, so it is part of it."""
    event, _ = _qualifier_world(["ana"])
    with_logo = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    event.partner_logo_url = None
    without = summarize_event(event, now=STARTS + dt.timedelta(days=2), finished_before={})
    assert with_logo.cache_key != without.cache_key


def test_a_stage_label_containing_of_keeps_its_whole_name_in_a_final_slot() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    event.config = {
        **CONFIG,
        "stages": [
            {**CONFIG["stages"][0], "label": "Semi A of the Invitational"},
            *CONFIG["stages"][1:],
        ],
    }
    summary = summarize_event(event, now=FINAL - dt.timedelta(hours=2), finished_before={})
    assert summary.field[0].label == "Semi A of the Invitational"


def test_a_newcomers_stage_seats_the_best_ranked_newcomers() -> None:
    event, users = _qualifier_world(["ana", "bob", "cleo", "dee", "eve", "fay"])
    # Seeds 1 to 4 hold the semis; the newcomers' final draws from what follows,
    # and only ana and eve have raced little enough to count as newcomers.
    veterans = {u.id: 9 for name, u in users.items() if name not in ("ana", "eve")}
    summary = summarize_event(
        event, now=NEWCOMERS - dt.timedelta(hours=2), finished_before=veterans
    )
    assert summary.stage_label == "Newcomers' final"
    assert [slot.user.twitch_username for slot in summary.field if slot.user] == ["eve"]


def test_playoffs_without_a_configured_stage_fall_back_to_the_field() -> None:
    event, _ = _qualifier_world(["ana", "bob"])
    event.config = {**CONFIG, "stages": []}
    summary = summarize_event(event, now=SEMI_A, finished_before={})
    assert summary.phase == "playoffs"
    assert summary.kind == "event_entrants"
    assert summary.caption == "Playoffs"


def test_a_wide_semi_keeps_its_line_up_on_the_card() -> None:
    """Nothing caps a semi's seeds, so the card caps the seats it draws."""
    event, _ = _qualifier_world([f"runner{i:02d}" for i in range(12)])
    event.config = {
        **CONFIG,
        "stages": [
            {**CONFIG["stages"][0], "seeds": list(range(1, 12))},
            {**CONFIG["stages"][1], "seeds": [12]},
            *CONFIG["stages"][2:],
        ],
    }
    summary = summarize_event(event, now=CUT + dt.timedelta(days=1), finished_before={})
    assert len(summary.field) == 8
    assert summary.field_overflow_count == 3


def test_a_wide_display_name_shrinks_the_winner_line() -> None:
    """Full-width glyphs come from the system fallback at twice the latin advance."""
    event, users = _qualifier_world(["ana", "bob"])
    users["bob"].twitch_display_name = "狭間の地の褪せ人チャンピオン十番勝負"
    event.races.append(
        _race("final:1", [_entry(users["bob"], 800_000), _entry(users["ana"], 900_000)])
    )
    wide = summarize_event(event, now=ENDS + dt.timedelta(days=1), finished_before={})
    users["bob"].twitch_display_name = "Bob"
    narrow = summarize_event(event, now=ENDS + dt.timedelta(days=1), finished_before={})
    assert wide.winner_font_size < narrow.winner_font_size


async def test_every_card_kind_renders_with_a_complete_context() -> None:
    """An attribute driven by a missing context key renders empty, not wrong."""
    running, _ = _qualifier_world(["ana", "bob", "cleo", "dee"])
    # A complete final ends the event whatever the clock says, so the winner
    # card needs its own world.
    crowned, users = _qualifier_world(["ana", "bob"])
    crowned.races.append(
        _race("final:1", [_entry(users["bob"], 800_000), _entry(users["ana"], 900_000)])
    )
    moments = {
        "event_upcoming": (running, STARTS - dt.timedelta(days=3)),
        "event_entrants": (running, STARTS + dt.timedelta(days=2)),
        "event_stage": (running, CUT + dt.timedelta(days=1)),
        "event_winner": (crowned, ENDS + dt.timedelta(days=1)),
    }
    for kind, (event, now) in moments.items():
        summary = summarize_event(event, now=now, finished_before={})
        assert summary.kind == kind
        ctx = await build_event_context(summary, avatar_lookup=_lookup, logo_lookup=_no_logo)
        svg = render_svg(summary.kind, ctx)
        assert 'font-size=""' not in svg
        assert 'dx=""' not in svg
