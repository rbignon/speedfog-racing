"""Discord announcements of new Set Seed and Random Seed records."""
# ruff: noqa: F401, F811

import asyncio
import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedfog_racing.models import RunMode, TrainingSessionStatus
from speedfog_racing.services import speedrun_records
from speedfog_racing.services.speedrun_records import check_speedrun_records, new_records

from .test_speedrun_service import (
    _add_run,
    _add_session,
    _run,
    _user,
    async_engine,
    async_session,
    pools,
)


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
    assert "record" in embed["title"]
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
