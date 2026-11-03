"""Discord announcements of new Set Seed and Random Seed records."""

import asyncio
import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.api import stats
from speedfog_racing.database import Base
from speedfog_racing.models import Pool, RunMode, TrainingSessionStatus
from speedfog_racing.services import speedrun_records
from speedfog_racing.services.speedrun_records import check_speedrun_records, new_records
from speedfog_racing.services.speedrun_service import load_counted_runs

from .test_speedrun_service import _add_run, _add_session, _run, _user


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def pools(async_session):
    async with async_session() as db:
        db.add(
            Pool(
                name="sprint",
                config={"name": "Sprint", "type": "race", "sort_order": 20, "layers_count": 15},
            )
        )
        await db.commit()


def _by_sub(changes):
    return {c.sub: c for c in changes}


def test_blind_run_beats_both_boards():
    old = _run("a", 5000, 1)
    new = _run("b", 4000, 2)
    changes = _by_sub(new_records([old, new], {new.run_id}))
    assert set(changes) == {"set", "random"}
    assert changes["set"].previous == old
    assert changes["random"].run == new


def test_replay_only_beats_set_seed():
    old = _run("a", 5000, 1)
    new = _run("b", 4000, 2, blind=False)
    assert set(_by_sub(new_records([old, new], {new.run_id}))) == {"set"}


def test_slower_run_is_no_record():
    old = _run("a", 3000, 1)
    new = _run("b", 4000, 2)
    assert new_records([old, new], {new.run_id}) == []


def test_tie_is_not_a_record():
    old = _run("a", 4000, 1)
    new = _run("b", 4000, 2)
    assert new_records([old, new], {new.run_id}) == []


def test_first_run_on_empty_board_is_a_record():
    new = _run("a", 4000, 1)
    changes = new_records([new], {new.run_id})
    assert {c.previous for c in changes} == {None}
    assert len(changes) == 2


def test_excluded_seed_blind_run_only_random():
    old = _run("a", 5000, 1)
    new = replace(_run("b", 4000, 2), seed_excluded=True)
    assert set(_by_sub(new_records([old, new], {new.run_id}))) == {"random"}


def test_a_purged_seed_run_still_holds_its_records():
    old = replace(_run("a", 3000, 1), seed_files_block="purged")
    new = _run("b", 4000, 2)
    assert new_records([old, new], {new.run_id}) == []


def test_only_the_fastest_new_run_of_a_board_is_a_record():
    old = _run("a", 5000, 1)
    n1 = _run("b", 4000, 2)
    n2 = _run("c", 3000, 2)
    changes = new_records([old, n1, n2], {n1.run_id, n2.run_id})
    assert {c.run.run_id for c in changes} == {n2.run_id}
    assert len(changes) == 2


def test_records_are_per_category():
    old = _run("a", 5000, 1, pool="sprint")
    new = _run("b", 4000, 2, pool="other")
    assert {c.category for c in new_records([old, new], {new.run_id})} == {"other"}


async def test_record_announced_once(async_session, pools):
    speedrun_records._announced.clear()
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        await _add_run(db, user=a, igt_ms=5_000_000, minute=1)
        p = await _add_run(db, user=b, igt_ms=4_000_000, minute=2)
        await db.commit()
        race_id = p.race_id
    send = AsyncMock()
    with (
        patch.object(speedrun_records, "async_session_maker", async_session),
        patch("speedfog_racing.discord._send_webhook", send),
    ):
        await check_speedrun_records(race_id=race_id)
        first = send.await_count
        await check_speedrun_records(race_id=race_id)
    assert first == 2  # Set Seed and Random Seed
    assert send.await_count == first
    embed = send.await_args_list[0].args[0]
    assert "Record" in embed["title"]
    assert f"?run={p.id}" in embed["url"]


async def test_session_record_announced(async_session, pools):
    speedrun_records._announced.clear()
    async with async_session() as db:
        a = await _user(db, "a")
        s = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 4_000_000)
        assert s.status == TrainingSessionStatus.FINISHED
        await db.commit()
        sid = s.id
    send = AsyncMock()
    with (
        patch.object(speedrun_records, "async_session_maker", async_session),
        patch("speedfog_racing.discord._send_webhook", send),
    ):
        await check_speedrun_records(session_id=sid)
    assert send.await_count == 2
    fields = {f["name"]: f["value"] for f in send.await_args_list[0].args[0]["fields"]}
    assert fields["Previous"] == "First record"


async def test_ranked_session_finish_schedules_check():
    from speedfog_racing.websocket.training import mod

    scheduled = MagicMock()
    with patch.object(mod, "schedule_speedrun_record_check", scheduled):
        mod.maybe_schedule_record_check(uuid.uuid4(), RunMode.SPEEDRUN)
        mod.maybe_schedule_record_check(uuid.uuid4(), RunMode.SET_SEED)
        mod.maybe_schedule_record_check(uuid.uuid4(), RunMode.NORMAL)
    assert scheduled.call_count == 2
    await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _clear_announced():
    speedrun_records._announced.clear()


def test_only_races_that_can_count_schedule_the_check():
    from speedfog_racing import discord

    def race(**kw):
        defaults = dict(
            id=uuid.uuid4(),
            mode=RunMode.NORMAL,
            daily_date=None,
            event_id=None,
            seed_was_seen=False,
            seed_played=False,
            rerolled_without_report=False,
            is_public=False,
            discord_event_id=None,
        )
        return MagicMock(**{**defaults, **kw})

    cases = [
        (race(), True),
        (race(mode=RunMode.SPEEDRUN), True),
        (race(mode=RunMode.SET_SEED), True),
        (race(daily_date=object()), True),
        (race(event_id=uuid.uuid4()), True),
        # A race on a SEEN seed counts nowhere, an event race included.
        (race(seed_was_seen=True), False),
        (race(event_id=uuid.uuid4(), seed_was_seen=True), False),
        # A reset keeps a community race off the boards, not an event race.
        (race(seed_played=True), False),
        (race(event_id=uuid.uuid4(), seed_played=True), True),
        (race(daily_date=object(), seed_played=True), True),
        # So does an unreported reroll; the admins reroll event races.
        (race(rerolled_without_report=True), False),
        (race(mode=RunMode.SPEEDRUN, rerolled_without_report=True), False),
        (race(event_id=uuid.uuid4(), rerolled_without_report=True), True),
    ]
    for r, expected in cases:
        with patch(
            "speedfog_racing.services.speedrun_records.schedule_speedrun_record_check"
        ) as scheduled:
            discord.fire_race_finished_notifications(r)
        assert scheduled.called is expected


async def test_record_check_loads_only_the_finished_runs_pool(async_session, pools):
    """A finish is compared with its own pool's runs; other pools are never
    loaded, and a faster run elsewhere neither blocks nor changes the record."""
    speedrun_records._announced.clear()
    async with async_session() as db:
        db.add(Pool(name="other", config={"name": "Other", "type": "race", "layers_count": 15}))
        a = await _user(db, "a")
        b = await _user(db, "b")
        await _add_run(db, user=a, igt_ms=1_000_000, minute=1, pool="other")
        await _add_run(db, user=a, igt_ms=5_000_000, minute=2)
        p = await _add_run(db, user=b, igt_ms=4_000_000, minute=3)
        await db.commit()
        race_id = p.race_id
    send = AsyncMock()
    real_load = speedrun_records.load_counted_runs
    loaded: list[list[str]] = []

    async def spy(db, **kwargs):
        runs = await real_load(db, **kwargs)
        loaded.append(sorted({r.pool for r in runs}))
        return runs

    with (
        patch.object(speedrun_records, "async_session_maker", async_session),
        patch.object(speedrun_records, "load_counted_runs", spy),
        patch("speedfog_racing.discord._send_webhook", send),
    ):
        await check_speedrun_records(race_id=race_id)
    assert loaded == [["sprint"]]
    assert send.await_count == 2


def test_replacing_a_pools_runs_keeps_the_other_pools_and_drops_derived_values():
    """The pool's slice goes by pool, archives included (no run listed
    twice), another pool's runs stay, and only the speedrun values derived
    from the list are dropped."""
    current = _run("a", 5000, 1)
    archived = replace(_run("b", 6000, 1), category="sprint@10")
    elsewhere = _run("c", 4000, 1, pool="other")
    new = _run("d", 3000, 2)
    stats._stats_cache["speedrun:runs"] = (123.0, [current, archived, elsewhere])
    stats._stats_cache["speedrun:overview"] = (123.0, None)
    stats._stats_cache["speedrun:board:sprint:set:0:race:0"] = (123.0, b"{}")
    stats._stats_cache["players"] = (123.0, None)

    stats.replace_speedrun_pool_runs(
        "sprint", [current, archived, new], generation=stats.speedrun_cache_generation()
    )

    expires_at, runs = stats._stats_cache["speedrun:runs"]
    assert sorted(r.run_id for r in runs) == sorted(
        r.run_id for r in (current, archived, elsewhere, new)
    )
    # The other pools' runs are no fresher: the list keeps its TTL.
    assert expires_at == 123.0
    assert set(stats._stats_cache) == {"speedrun:runs", "players"}


def test_without_a_cached_list_no_single_pool_list_is_cached():
    """A list of one pool would hide every other pool's runs until the TTL."""
    stats._stats_cache["speedrun:overview"] = (123.0, None)
    stats.replace_speedrun_pool_runs(
        "sprint", [_run("a", 5000, 1)], generation=stats.speedrun_cache_generation()
    )
    assert not any(key.startswith("speedrun:") for key in stats._stats_cache)


def test_a_swap_whose_load_overlapped_another_write_drops_the_whole_list():
    """Two finishes in a pool, loaded concurrently: either load may predate
    the other's finish, so the second swap cannot trust its own and every
    speedrun value is dropped (the next request reloads them all)."""
    stats._stats_cache["speedrun:runs"] = (123.0, [_run("a", 5000, 1)])
    loaded_at = stats.speedrun_cache_generation()
    stats.replace_speedrun_pool_runs("sprint", [_run("b", 4000, 2)], generation=loaded_at)
    assert "speedrun:runs" in stats._stats_cache
    stats.replace_speedrun_pool_runs("sprint", [_run("c", 3000, 3)], generation=loaded_at)
    assert not any(key.startswith("speedrun:") for key in stats._stats_cache)


async def test_record_check_puts_a_counted_finish_on_the_cached_boards(async_session, pools):
    """Any counted finish shows at once, a record or not; a finish that counts
    on no board leaves the cache alone."""
    async with async_session() as db:
        db.add(Pool(name="other", config={"name": "Other", "type": "race", "layers_count": 15}))
        a = await _user(db, "a")
        b = await _user(db, "b")
        elsewhere = await _add_run(db, user=a, igt_ms=1_000_000, minute=1, pool="other")
        await _add_run(db, user=a, igt_ms=5_000_000, minute=2)
        await db.commit()
        stats._stats_cache["speedrun:runs"] = (123.0, await load_counted_runs(db))
        stats._stats_cache["speedrun:overview"] = (123.0, None)
        unranked = await _add_run(db, user=b, igt_ms=3_000_000, minute=3, seed_was_seen=True)
        slower = await _add_run(db, user=b, igt_ms=6_000_000, minute=4)
        await db.commit()
    with (
        patch.object(speedrun_records, "async_session_maker", async_session),
        patch("speedfog_racing.discord._send_webhook", AsyncMock()),
    ):
        await check_speedrun_records(race_id=unranked.race_id)
        assert "speedrun:overview" in stats._stats_cache
        await check_speedrun_records(race_id=slower.race_id)
    run_ids = {r.run_id for r in stats._stats_cache["speedrun:runs"][1]}
    assert {slower.id, elsewhere.id} <= run_ids
    assert unranked.id not in run_ids
    assert "speedrun:overview" not in stats._stats_cache


async def test_a_write_during_the_record_checks_load_drops_the_whole_list(async_session, pools):
    """The check reads the generation before its load: a write landing during
    the load (here an exclusion, then a full reload cached after it) makes the
    check drop every speedrun value instead of swapping an older slice in."""
    async with async_session() as db:
        a = await _user(db, "a")
        p = await _add_run(db, user=a, igt_ms=5_000_000, minute=1)
        await db.commit()
    real_load = speedrun_records.load_counted_runs

    async def load_then_write(db, **kwargs):
        runs = await real_load(db, **kwargs)
        stats.forget_speedrun_caches()
        stats._stats_cache["speedrun:runs"] = (123.0, await real_load(db))
        return runs

    with (
        patch.object(speedrun_records, "async_session_maker", async_session),
        patch.object(speedrun_records, "load_counted_runs", load_then_write),
        patch("speedfog_racing.discord._send_webhook", AsyncMock()),
    ):
        await check_speedrun_records(race_id=p.race_id)
    assert not any(key.startswith("speedrun:") for key in stats._stats_cache)
