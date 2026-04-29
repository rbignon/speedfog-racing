"""Integration tests for the per-connection chat broadcast filters.

Verifies that ``RaceRoom.broadcast_chat_public`` and
``broadcast_chat_participants`` deliver only to connections that pass
the chat_access helpers, across the matrix from
``docs/specs/2026-04-28-public-chat-lock-design.md``.

The chat_access helpers themselves are unit-tested in
``test_chat_access.py``; here we focus on the wiring inside
``RaceRoom``.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from speedfog_racing.models import (
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import RaceRoom, SpectatorConnection


def _make_user(role: UserRole = UserRole.USER) -> User:
    return User(
        id=uuid4(),
        twitch_id=f"u-{uuid4()}",
        twitch_username=f"u-{uuid4().hex[:6]}",
        twitch_display_name="Viewer",
        twitch_avatar_url=None,
        role=role,
    )


def _make_race(
    *,
    status: RaceStatus,
    started_at: datetime | None = None,
    late_join_window_minutes: int | None = None,
    race_duration_minutes: int | None = None,
) -> Race:
    organizer = _make_user(role=UserRole.ORGANIZER)
    race = Race(
        id=uuid4(),
        name="R",
        organizer_id=organizer.id,
        organizer=organizer,
        status=status,
        is_public=True,
        open_registration=True,
        max_participants=10,
        started_at=started_at,
        late_join_window_minutes=late_join_window_minutes,
        race_duration_minutes=race_duration_minutes,
        created_at=datetime.now(UTC),
    )
    race.participants = []
    race.casters = []
    race.seed = None
    return race


def _conn(
    *,
    role: str | None = None,
    user_id: bool = True,
    participant_status: ParticipantStatus | None = None,
) -> SpectatorConnection:
    """Build a SpectatorConnection with a mocked websocket.send_text."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return SpectatorConnection(
        websocket=ws,
        user_id=uuid4() if user_id else None,
        role=role,
        participant_status=participant_status,
    )


def _add(room: RaceRoom, conn: SpectatorConnection) -> None:
    room.spectators[conn.connection_id] = conn


def _running_race(*, late_join_open: bool) -> Race:
    started = datetime.now(UTC) - (
        timedelta(minutes=5) if late_join_open else timedelta(minutes=45)
    )
    return _make_race(
        status=RaceStatus.RUNNING,
        started_at=started,
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )


# -- broadcast_chat_public ---------------------------------------------------


class TestBroadcastChatPublic:
    @pytest.mark.asyncio
    async def test_setup_sends_to_no_one(self):
        """SETUP race: nobody can read public chat, even privileged roles."""
        race = _make_race(status=RaceStatus.SETUP)
        room = RaceRoom(race_id=race.id)
        spectator = _conn()
        organizer = _conn(role="organizer")
        participant = _conn(role="participant", participant_status=ParticipantStatus.REGISTERED)
        for c in (spectator, organizer, participant):
            _add(room, c)

        await room.broadcast_chat_public("hello", race)

        spectator.websocket.send_text.assert_not_called()
        organizer.websocket.send_text.assert_not_called()
        participant.websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_running_late_join_open_filters_correctly(self):
        race = _running_race(late_join_open=True)
        room = RaceRoom(race_id=race.id)

        anonymous = _conn(user_id=False)
        spectator = _conn()
        active_participant = _conn(role="participant", participant_status=ParticipantStatus.PLAYING)
        finished_participant = _conn(
            role="participant", participant_status=ParticipantStatus.FINISHED
        )
        abandoned_participant = _conn(
            role="participant", participant_status=ParticipantStatus.ABANDONED
        )
        organizer = _conn(role="organizer")
        admin = _conn(role="admin")
        caster = _conn(role="caster")

        for c in (
            anonymous,
            spectator,
            active_participant,
            finished_participant,
            abandoned_participant,
            organizer,
            admin,
            caster,
        ):
            _add(room, c)

        await room.broadcast_chat_public("spoiler!", race)

        # Locked while late-join is still open: anonymous, authenticated
        # spectator (could late-join), active participant, and every
        # privileged role that is not also a terminated participant.
        anonymous.websocket.send_text.assert_not_called()
        spectator.websocket.send_text.assert_not_called()
        active_participant.websocket.send_text.assert_not_called()
        organizer.websocket.send_text.assert_not_called()
        admin.websocket.send_text.assert_not_called()
        caster.websocket.send_text.assert_not_called()

        # Unlocked: terminal-status participants only.
        finished_participant.websocket.send_text.assert_called_once()
        abandoned_participant.websocket.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_running_late_join_closed_filters_correctly(self):
        race = _running_race(late_join_open=False)
        room = RaceRoom(race_id=race.id)

        spectator = _conn()
        active_participant = _conn(role="participant", participant_status=ParticipantStatus.PLAYING)
        finished_participant = _conn(
            role="participant", participant_status=ParticipantStatus.FINISHED
        )
        organizer = _conn(role="organizer")
        admin = _conn(role="admin")
        caster = _conn(role="caster")

        for c in (
            spectator,
            active_participant,
            finished_participant,
            organizer,
            admin,
            caster,
        ):
            _add(room, c)

        await room.broadcast_chat_public("hello", race)

        active_participant.websocket.send_text.assert_not_called()
        spectator.websocket.send_text.assert_called_once()
        finished_participant.websocket.send_text.assert_called_once()
        organizer.websocket.send_text.assert_called_once()
        admin.websocket.send_text.assert_called_once()
        caster.websocket.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_running_no_late_join_window_unlocks_for_spectators(self):
        # Race configured without a late-join window: the registration
        # window is closed from t=0, so spectators should see public chat
        # immediately and active participants must not.
        race = _make_race(
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=1),
            late_join_window_minutes=None,
        )
        room = RaceRoom(race_id=race.id)
        spectator = _conn()
        active_participant = _conn(role="participant", participant_status=ParticipantStatus.PLAYING)
        for c in (spectator, active_participant):
            _add(room, c)

        await room.broadcast_chat_public("hello", race)

        spectator.websocket.send_text.assert_called_once()
        active_participant.websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_finished_race_sends_to_everyone_including_anonymous(self):
        race = _make_race(status=RaceStatus.FINISHED)
        room = RaceRoom(race_id=race.id)
        anonymous = _conn(user_id=False)
        spectator = _conn()
        finished_participant = _conn(
            role="participant", participant_status=ParticipantStatus.FINISHED
        )
        organizer = _conn(role="organizer")
        for c in (anonymous, spectator, finished_participant, organizer):
            _add(room, c)

        await room.broadcast_chat_public("gg!", race)

        anonymous.websocket.send_text.assert_called_once()
        spectator.websocket.send_text.assert_called_once()
        finished_participant.websocket.send_text.assert_called_once()
        organizer.websocket.send_text.assert_called_once()


# -- broadcast_chat_participants --------------------------------------------


class TestBroadcastChatParticipants:
    @pytest.mark.asyncio
    async def test_filters_by_race_role(self):
        race = _make_race(status=RaceStatus.SETUP)
        room = RaceRoom(race_id=race.id)

        anonymous = _conn(user_id=False)
        spectator = _conn()  # authenticated, no role
        participant = _conn(role="participant", participant_status=ParticipantStatus.REGISTERED)
        organizer = _conn(role="organizer")
        admin = _conn(role="admin")
        caster = _conn(role="caster")

        for c in (anonymous, spectator, participant, organizer, admin, caster):
            _add(room, c)

        await room.broadcast_chat_participants("ready?")

        anonymous.websocket.send_text.assert_not_called()
        spectator.websocket.send_text.assert_not_called()
        participant.websocket.send_text.assert_called_once()
        organizer.websocket.send_text.assert_called_once()
        admin.websocket.send_text.assert_called_once()
        caster.websocket.send_text.assert_called_once()


# -- prove the helpers see real role/status fields, not mocks ---------------


class TestSpectatorConnectionShape:
    def test_participant_status_defaults_to_none(self):
        conn = SpectatorConnection(websocket=AsyncMock())
        assert conn.participant_status is None

    def test_participant_status_carries_value(self):
        conn = SpectatorConnection(
            websocket=AsyncMock(),
            participant_status=ParticipantStatus.PLAYING,
        )
        assert conn.participant_status == ParticipantStatus.PLAYING


# -- room.set_participant_status (C4 transition hook) -----------------------


class TestSetParticipantStatus:
    @pytest.mark.parametrize(
        "terminal_status", [ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED]
    )
    def test_updates_all_connections_for_user(self, terminal_status):
        """Multi-tab: every connection of the user gets the new status.

        Parametrized over the two terminal statuses so the abandon path
        (api/races.py + inactivity_monitor.py) is covered alongside the
        finish path (mod.py).
        """
        room = RaceRoom(race_id=uuid4())
        user_id = uuid4()
        tab1 = SpectatorConnection(
            websocket=AsyncMock(),
            user_id=user_id,
            role="participant",
            participant_status=ParticipantStatus.PLAYING,
        )
        tab2 = SpectatorConnection(
            websocket=AsyncMock(),
            user_id=user_id,
            role="participant",
            participant_status=ParticipantStatus.PLAYING,
        )
        unrelated = SpectatorConnection(
            websocket=AsyncMock(),
            user_id=uuid4(),
            role="participant",
            participant_status=ParticipantStatus.PLAYING,
        )
        for c in (tab1, tab2, unrelated):
            room.spectators[c.connection_id] = c

        room.set_participant_status(user_id, terminal_status)

        assert tab1.participant_status == terminal_status
        assert tab2.participant_status == terminal_status
        # Unrelated user untouched.
        assert unrelated.participant_status == ParticipantStatus.PLAYING

    def test_no_match_is_a_noop(self):
        room = RaceRoom(race_id=uuid4())
        room.set_participant_status(uuid4(), ParticipantStatus.FINISHED)
        # Should not raise, and no connection to inspect; reaching here is enough.

    @pytest.mark.asyncio
    async def test_finish_then_broadcast_reaches_just_finished_participant(self):
        """After set_participant_status(FINISHED), the broadcast filter
        includes the connection of the just-finished participant."""
        race = _running_race(late_join_open=True)
        room = RaceRoom(race_id=race.id)
        user_id = uuid4()
        finisher = SpectatorConnection(
            websocket=AsyncMock(),
            user_id=user_id,
            role="participant",
            participant_status=ParticipantStatus.PLAYING,
        )
        room.spectators[finisher.connection_id] = finisher

        # Pre-state: locked (active participant during late-join).
        await room.broadcast_chat_public("first", race)
        finisher.websocket.send_text.assert_not_called()

        # Transition.
        room.set_participant_status(user_id, ParticipantStatus.FINISHED)

        await room.broadcast_chat_public("you finished!", race)
        finisher.websocket.send_text.assert_called_once()
