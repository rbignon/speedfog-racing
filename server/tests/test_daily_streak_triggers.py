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


@pytest.mark.asyncio
async def test_update_b_consumes_freeze_for_missed_day(streak_async_session) -> None:
    """Update B applies the close-day branch for each user with an active
    streak who did not qualify yesterday.

    Three users:
    - u_freeze: 5-day streak, 1 freeze. Misses yesterday. Should keep
      streak=5, freeze=0, and gain a daily_streak_freezes row.
    - u_break: 3-day streak, 0 freezes. Misses yesterday. Should break to
      streak=0, best stays 10.
    - u_safe: 7-day streak, 1 freeze, qualified yesterday. Untouched.
    """
    from datetime import date

    from sqlalchemy import select

    from speedfog_racing.models import DailyStreakFreeze, User
    from speedfog_racing.services.daily_streak_service import (
        apply_close_day_for_all_users,
    )

    missed = date(2026, 5, 11)
    async with streak_async_session() as db:
        u_freeze = User(
            twitch_id="b1",
            twitch_username="b1",
            daily_current_streak=5,
            daily_best_streak=5,
            daily_freeze_count=1,
            daily_last_qualifying_date=date(2026, 5, 10),
        )
        u_break = User(
            twitch_id="b2",
            twitch_username="b2",
            daily_current_streak=3,
            daily_best_streak=10,
            daily_freeze_count=0,
            daily_last_qualifying_date=date(2026, 5, 10),
        )
        u_safe = User(
            twitch_id="b3",
            twitch_username="b3",
            daily_current_streak=7,
            daily_best_streak=7,
            daily_freeze_count=1,
            daily_last_qualifying_date=missed,
        )
        db.add_all([u_freeze, u_break, u_safe])
        await db.commit()

        changed = await apply_close_day_for_all_users(db, missed=missed)
        await db.commit()
        assert changed == 2  # u_freeze and u_break

        await db.refresh(u_freeze)
        assert u_freeze.daily_current_streak == 5
        assert u_freeze.daily_freeze_count == 0
        await db.refresh(u_break)
        assert u_break.daily_current_streak == 0
        assert u_break.daily_best_streak == 10
        await db.refresh(u_safe)
        assert u_safe.daily_current_streak == 7
        assert u_safe.daily_freeze_count == 1

        freezes = (
            await db.execute(select(DailyStreakFreeze.user_id, DailyStreakFreeze.daily_date))
        ).all()
        assert (u_freeze.id, missed) in freezes
        assert all(uid != u_break.id for uid, _ in freezes)
        assert all(uid != u_safe.id for uid, _ in freezes)


@pytest.mark.asyncio
async def test_update_b_idempotent_on_rerun(streak_async_session) -> None:
    """Calling apply_close_day_for_all_users twice with the same missed
    date does not double-consume a freeze, because the second pass finds
    the freeze row already present and skips the user."""
    from datetime import date

    from sqlalchemy import select

    from speedfog_racing.models import DailyStreakFreeze, User
    from speedfog_racing.services.daily_streak_service import (
        apply_close_day_for_all_users,
    )

    missed = date(2026, 5, 11)
    async with streak_async_session() as db:
        u = User(
            twitch_id="idem1",
            twitch_username="idem1",
            daily_current_streak=5,
            daily_best_streak=5,
            daily_freeze_count=1,
            daily_last_qualifying_date=date(2026, 5, 10),
        )
        db.add(u)
        await db.commit()

        await apply_close_day_for_all_users(db, missed=missed)
        await db.commit()
        await db.refresh(u)
        first_freezes = u.daily_freeze_count

        # Second call: no further change.
        await apply_close_day_for_all_users(db, missed=missed)
        await db.commit()
        await db.refresh(u)
        assert u.daily_freeze_count == first_freezes  # still 0

        rows = (
            (await db.execute(select(DailyStreakFreeze).where(DailyStreakFreeze.user_id == u.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_reroll_rolls_back_streak_for_today_qualifiers(streak_async_session) -> None:
    """After a reroll wipes zone_history for the current daily, the
    streak service re-derives state from scratch. A user whose only
    qualifying participation was today's wiped daily ends with
    current_streak = 0 but best_streak preserved.
    """
    from datetime import date

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.services.daily_streak_service import (
        rollback_streak_for_reroll,
    )

    today = date(2026, 5, 12)
    async with streak_async_session() as db:
        user = User(
            twitch_id="rr1",
            twitch_username="rr1",
            daily_current_streak=1,
            daily_best_streak=1,
            daily_freeze_count=0,
            daily_last_qualifying_date=today,
        )
        db.add(user)
        await db.flush()
        race = Race(
            name="Daily Seed - 2026-05-12",
            organizer_id=user.id,
            daily_date=today,
            exclude_from_elo=True,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        # Simulating post-reroll: the participant row is back to REGISTERED
        # with zone_history wiped.
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.REGISTERED,
            zone_history=None,
        )
        db.add(participant)
        await db.commit()

        # Mirror production: race is loaded with participants + user eager.
        race = (
            await db.execute(
                select(Race)
                .where(Race.id == race.id)
                .options(selectinload(Race.participants).selectinload(Participant.user))
            )
        ).scalar_one()

        await rollback_streak_for_reroll(db, race, today=today)
        await db.commit()

        await db.refresh(user)
        assert user.daily_current_streak == 0
        assert user.daily_best_streak == 1  # high water mark preserved
        assert user.daily_last_qualifying_date is None


@pytest.mark.asyncio
async def test_reroll_rollback_is_noop_for_non_daily_race(streak_async_session) -> None:
    """A reroll on a non-daily race must not touch streak state."""
    from datetime import date

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.services.daily_streak_service import (
        rollback_streak_for_reroll,
    )

    async with streak_async_session() as db:
        user = User(
            twitch_id="rr2",
            twitch_username="rr2",
            daily_current_streak=5,
            daily_best_streak=5,
            daily_freeze_count=1,
            daily_last_qualifying_date=date(2026, 5, 11),
        )
        db.add(user)
        await db.flush()
        race = Race(
            name="Some race",
            organizer_id=user.id,
            daily_date=None,
            exclude_from_elo=False,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.REGISTERED,
            zone_history=None,
        )
        db.add(participant)
        await db.commit()

        await rollback_streak_for_reroll(db, race, today=date(2026, 5, 12))
        await db.commit()
        await db.refresh(user)
        assert user.daily_current_streak == 5
        assert user.daily_best_streak == 5
        assert user.daily_freeze_count == 1
        assert user.daily_last_qualifying_date == date(2026, 5, 11)


@pytest.mark.asyncio
async def test_broadcast_event_flag_only_runs_streak_on_qualification_crossing(
    streak_async_session,
) -> None:
    """The handler-side ``prev_zone_history_len`` guard must gate the streak
    service so a participant who keeps appending zones after passing zone 2
    does not re-trigger ``_apply_daily_streak`` on every event_flag.

    Spec: "at most once per user per daily" (see Update A in the daily-streak
    design). Removing the guard would re-open a session and SELECT the
    participant for every post-qualification event_flag.
    """
    from datetime import date

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.websocket.race.mod import RaceModHandler

    async with streak_async_session() as db:
        user = User(twitch_id="bc1", twitch_username="bc1")
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
            zone_history=[{"node_id": "start", "igt_ms": 0, "type": "spawn"}],
        )
        db.add(participant)
        await db.commit()
        # Eager-load .race so _broadcast_after_event_flag can read daily_date
        # without re-issuing queries.
        await db.refresh(participant, attribute_names=["race"])

    handler = RaceModHandler(MagicMock(), race.id, streak_async_session)
    handler._apply_daily_streak = AsyncMock()  # type: ignore[method-assign]

    await handler._broadcast_after_event_flag(
        participant,
        "n2",
        None,
        is_first_visit=False,
        prev_zone_history_len=2,
    )
    handler._apply_daily_streak.assert_not_awaited()

    await handler._broadcast_after_event_flag(
        participant,
        "n3",
        None,
        is_first_visit=False,
        prev_zone_history_len=1,
    )
    handler._apply_daily_streak.assert_awaited_once_with(participant)


@pytest.mark.asyncio
async def test_broadcast_zone_query_runs_streak_on_qualification_crossing(
    streak_async_session,
) -> None:
    """A backtrack written via zone_query can also be the spawn -> 2 crossing
    (rare: a death or quit-out before crossing the first fog). The race
    subclass must fire the streak service in that case too, mirroring the
    event_flag dispatch path."""
    from datetime import date

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.websocket.race.mod import RaceModHandler

    async with streak_async_session() as db:
        user = User(twitch_id="zq1", twitch_username="zq1")
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
        new_participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[{"node_id": "start", "igt_ms": 0, "type": "spawn"}],
        )
        db.add(new_participant)
        await db.commit()
        participant = (
            await db.execute(
                select(Participant)
                .where(Participant.id == new_participant.id)
                .options(
                    selectinload(Participant.race).selectinload(Race.seed),
                    selectinload(Participant.race).selectinload(Race.participants),
                )
            )
        ).scalar_one()
        race_id = race.id

    handler = RaceModHandler(MagicMock(), race_id, streak_async_session)
    handler._apply_daily_streak = AsyncMock()  # type: ignore[method-assign]

    await handler._broadcast_after_zone_query(
        participant,
        is_first_visit=False,
        prev_zone_history_len=2,
    )
    handler._apply_daily_streak.assert_not_awaited()

    await handler._broadcast_after_zone_query(
        participant,
        is_first_visit=False,
        prev_zone_history_len=1,
    )
    handler._apply_daily_streak.assert_awaited_once_with(participant)
