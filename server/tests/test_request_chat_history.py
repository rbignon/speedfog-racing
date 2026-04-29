"""Tests for the ``request_chat_history`` WebSocket message.

The frontend sends this when its locally-computed ``publicAccess``
transitions from locked to readable. The server revalidates with the
chat_access helpers and sends the history if access is granted, or
silently ignores otherwise. For the public channel, the cached
``participant_status`` is refreshed from DB so a participant who
finished mid-race no longer needs a reconnect to see the unlock.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.spectator import RaceSpectatorHandler


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_race_and_participant(
    session_maker,
    *,
    race_status: RaceStatus,
    participant_status: ParticipantStatus,
    started_at: datetime | None = None,
    late_join_window_minutes: int | None = 30,
    public_message: str = "spoiler!",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a race + organizer + one participant + one public message.

    Returns ``(race_id, participant_user_id)``.
    """
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"org-{uuid.uuid4()}",
            twitch_username=f"org-{uuid.uuid4().hex[:6]}",
            twitch_display_name="Org",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id=f"p-{uuid.uuid4()}",
            twitch_username=f"p-{uuid.uuid4().hex[:6]}",
            twitch_display_name="P",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()

        race = Race(
            name="R",
            organizer_id=organizer.id,
            status=race_status,
            started_at=started_at,
            late_join_window_minutes=late_join_window_minutes,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=participant_status,
        )
        db.add(participant)

        db.add(
            ChatMessage(
                race_id=race.id,
                channel=ChatChannel.PUBLIC,
                user_id=organizer.id,
                message=public_message,
            )
        )
        await db.commit()
        return race.id, player.id


def _make_handler(session_maker, race_id: uuid.UUID) -> RaceSpectatorHandler:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return RaceSpectatorHandler(ws, race_id, session_maker)


async def _last_sent_payload(handler: RaceSpectatorHandler) -> dict | None:
    if not handler.websocket.send_text.await_args_list:
        return None
    return json.loads(handler.websocket.send_text.await_args_list[-1].args[0])


# -- public channel ---------------------------------------------------------


@pytest.mark.asyncio
async def test_public_request_silently_rejected_when_locked(session_maker):
    """Active participant during late-join: request must be ignored."""
    race_id, user_id = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.PLAYING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = user_id
    handler._conn.role = "participant"
    handler._conn.participant_status = ParticipantStatus.PLAYING

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "public"}
    )

    handler.websocket.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_public_request_returns_history_when_unlocked(session_maker):
    """Spectator after late-join closed: history is sent."""
    race_id, _ = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.PLAYING,
        started_at=datetime.now(UTC) - timedelta(minutes=45),
        late_join_window_minutes=30,
    )
    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = uuid.uuid4()
    # No role: pure spectator. Late-join is closed -> unlocked.

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "public"}
    )

    payload = await _last_sent_payload(handler)
    assert payload is not None
    assert payload["type"] == "chat_history"
    assert payload["channel"] == "public"
    assert any(m["message"] == "spoiler!" for m in payload["messages"])


@pytest.mark.asyncio
async def test_public_request_refreshes_participant_status_from_db(session_maker):
    """Participant cached as PLAYING but DB says FINISHED -> unlock + history."""
    race_id, user_id = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.FINISHED,  # already finished in DB
        started_at=datetime.now(UTC) - timedelta(minutes=5),  # late-join still open
        late_join_window_minutes=30,
    )
    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = user_id
    handler._conn.role = "participant"
    handler._conn.participant_status = ParticipantStatus.PLAYING  # stale cache

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "public"}
    )

    # Cache was refreshed from DB and access granted.
    assert handler._conn.participant_status == ParticipantStatus.FINISHED
    payload = await _last_sent_payload(handler)
    assert payload is not None
    assert payload["channel"] == "public"


@pytest.mark.asyncio
async def test_public_request_for_unknown_race_silently_ignored(session_maker):
    handler = _make_handler(session_maker, uuid.uuid4())
    handler._conn.user_id = uuid.uuid4()

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "public"}
    )

    handler.websocket.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_public_request_locked_for_organizer_during_late_join(session_maker):
    """Race role does not unlock by itself: organizers follow the same
    spectator rules (locked while late-join is open)."""
    race_id, _ = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.PLAYING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=30,
    )
    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = uuid.uuid4()
    handler._conn.role = "organizer"

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "public"}
    )

    handler.websocket.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_payload_silently_ignored(session_maker):
    race_id, _ = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.FINISHED,
        participant_status=ParticipantStatus.FINISHED,
    )
    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = uuid.uuid4()

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "spoiler"}
    )

    handler.websocket.send_text.assert_not_called()


# -- participants channel ---------------------------------------------------


@pytest.mark.asyncio
async def test_participants_request_returns_history_for_role(session_maker):
    race_id, user_id = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.PLAYING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    # Add a participants-channel message.
    async with session_maker() as db:
        race = await db.get(Race, race_id)
        assert race is not None
        db.add(
            ChatMessage(
                race_id=race_id,
                channel=ChatChannel.PARTICIPANTS,
                user_id=user_id,
                message="ready?",
            )
        )
        await db.commit()

    handler = _make_handler(session_maker, race_id)
    handler._conn.user_id = user_id
    handler._conn.role = "participant"

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "participants"}
    )

    payload = await _last_sent_payload(handler)
    assert payload is not None
    assert payload["channel"] == "participants"
    assert any(m["message"] == "ready?" for m in payload["messages"])


@pytest.mark.asyncio
async def test_participants_request_silently_rejected_for_anonymous(session_maker):
    race_id, _ = await _seed_race_and_participant(
        session_maker,
        race_status=RaceStatus.RUNNING,
        participant_status=ParticipantStatus.PLAYING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    handler = _make_handler(session_maker, race_id)
    # No user_id, no role.

    await handler._handle_request_chat_history(
        {"type": "request_chat_history", "channel": "participants"}
    )

    handler.websocket.send_text.assert_not_called()
