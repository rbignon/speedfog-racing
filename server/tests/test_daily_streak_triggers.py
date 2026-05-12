"""Integration tests for the daily-streak WS dispatch path."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.websocket.race.manager import (
    ConnectionManager,
    ModConnection,
    SpectatorConnection,
)
from speedfog_racing.websocket.schemas import DailyStreakUpdateMessage


@pytest.fixture
async def streak_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def streak_async_session(streak_async_engine):
    return async_sessionmaker(streak_async_engine, class_=AsyncSession, expire_on_commit=False)


def test_daily_streak_update_message_serialization() -> None:
    msg = DailyStreakUpdateMessage(current=7, best=42, freeze_count=1)
    payload = msg.model_dump()
    assert payload == {
        "type": "daily_streak_update",
        "current": 7,
        "best": 42,
        "freeze_count": 1,
    }


def test_daily_streak_update_message_omits_extra_fields() -> None:
    """The schema accepts only the documented fields."""
    msg = DailyStreakUpdateMessage(current=0, best=0, freeze_count=0)
    assert msg.model_dump().keys() == {"type", "current", "best", "freeze_count"}


async def test_send_daily_streak_update_routes_to_all_user_connections() -> None:
    """The helper iterates both mods and spectators and sends to every
    connection matching ``user_id``. Two spectator tabs + one mod = three
    send_text calls. Connections for other users are skipped."""
    manager = ConnectionManager()
    race_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    room = manager.get_or_create_room(race_id)

    def make_ws() -> MagicMock:
        ws = MagicMock()
        ws.send_text = AsyncMock()
        return ws

    target_mod_ws = make_ws()
    target_spec_ws_a = make_ws()
    target_spec_ws_b = make_ws()
    other_spec_ws = make_ws()

    target_mod = ModConnection(
        websocket=target_mod_ws,
        participant_id=uuid.uuid4(),
        user_id=user_id,
    )
    target_spec_a = SpectatorConnection(
        websocket=target_spec_ws_a,
        user_id=user_id,
    )
    target_spec_b = SpectatorConnection(
        websocket=target_spec_ws_b,
        user_id=user_id,
    )
    other_spec = SpectatorConnection(
        websocket=other_spec_ws,
        user_id=other_user_id,
    )

    room.mods[target_mod.participant_id] = target_mod
    room.spectators[target_spec_a.connection_id] = target_spec_a
    room.spectators[target_spec_b.connection_id] = target_spec_b
    room.spectators[other_spec.connection_id] = other_spec

    await manager.send_daily_streak_update_to_user(
        race_id, user_id, current=8, best=42, freeze_count=1
    )

    target_mod_ws.send_text.assert_awaited_once()
    target_spec_ws_a.send_text.assert_awaited_once()
    target_spec_ws_b.send_text.assert_awaited_once()
    other_spec_ws.send_text.assert_not_awaited()

    sent_payload = target_mod_ws.send_text.await_args.args[0]
    assert '"type":"daily_streak_update"' in sent_payload
    assert '"current":8' in sent_payload
    assert '"best":42' in sent_payload
    assert '"freeze_count":1' in sent_payload


async def test_send_daily_streak_update_noop_on_missing_room() -> None:
    """No room means no work; the helper returns silently."""
    manager = ConnectionManager()
    await manager.send_daily_streak_update_to_user(
        uuid.uuid4(), uuid.uuid4(), current=0, best=0, freeze_count=0
    )
    # No assertion needed; reaching here means no exception was raised.


async def test_send_daily_streak_update_evicts_failed_connections() -> None:
    """When a send raises, the failing connection is popped from the room
    (mirroring the existing send_to_mod / broadcast_to_spectators pattern)."""
    manager = ConnectionManager()
    race_id = uuid.uuid4()
    user_id = uuid.uuid4()
    room = manager.get_or_create_room(race_id)

    def make_ws(fail: bool = False) -> MagicMock:
        ws = MagicMock()
        ws.send_text = AsyncMock(side_effect=RuntimeError("boom") if fail else None)
        return ws

    bad_mod = ModConnection(
        websocket=make_ws(fail=True),
        participant_id=uuid.uuid4(),
        user_id=user_id,
    )
    bad_spec = SpectatorConnection(
        websocket=make_ws(fail=True),
        user_id=user_id,
    )
    good_spec = SpectatorConnection(
        websocket=make_ws(fail=False),
        user_id=user_id,
    )

    room.mods[bad_mod.participant_id] = bad_mod
    room.spectators[bad_spec.connection_id] = bad_spec
    room.spectators[good_spec.connection_id] = good_spec

    await manager.send_daily_streak_update_to_user(
        race_id, user_id, current=1, best=1, freeze_count=0
    )

    assert bad_mod.participant_id not in room.mods
    assert bad_spec.connection_id not in room.spectators
    assert good_spec.connection_id in room.spectators


@pytest.mark.asyncio
async def test_event_flag_crossing_zone_two_triggers_update_a(
    streak_async_session,
    monkeypatch,
) -> None:
    """When a participant on a daily crosses ``len(zone_history) >= 2`` via
    an event_flag, calling the evaluator + the WS dispatch helper composes
    the streak transition and pushes the new state. Contract test: we drive
    the helpers directly rather than spinning a real WS connection.
    """
    from datetime import date

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.services.daily_streak_service import (
        evaluate_qualification_for_participant,
    )
    from speedfog_racing.websocket.race import manager as manager_module

    pushed: list[tuple] = []

    async def fake_push(race_id, user_id, *, current, best, freeze_count):
        pushed.append((race_id, user_id, current, best, freeze_count))

    monkeypatch.setattr(
        manager_module.manager,
        "send_daily_streak_update_to_user",
        fake_push,
    )

    async with streak_async_session() as db:
        user = User(twitch_id="ef1", twitch_username="ef1")
        db.add(user)
        await db.flush()
        race = Race(
            name="Daily Seed - 2026-05-12",
            organizer_id=user.id,
            daily_date=date(2026, 5, 12),
            exclude_from_elo=True,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[
                {"node_id": "start", "igt_ms": 0, "type": "fog"},
                {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
            ],
        )
        db.add(participant)
        await db.commit()

        new_state = await evaluate_qualification_for_participant(db, participant)
        assert new_state is not None
        await manager_module.manager.send_daily_streak_update_to_user(
            race.id,
            user.id,
            current=new_state.current_streak,
            best=new_state.best_streak,
            freeze_count=new_state.freeze_count,
        )

    assert pushed == [(race.id, user.id, 1, 1, 0)]
