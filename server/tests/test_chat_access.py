"""Unit tests for ``services.chat_access``.

Covers the public-channel matrix documented in the "Chat System" section
of ``docs/PROTOCOL.md`` for both reads and writes, plus the
``race_role`` resolution and the small predicates.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from speedfog_racing.models import (
    Caster,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.services.chat_access import (
    can_read_participants_chat,
    can_read_public_chat,
    can_write_public_chat,
    is_active_participant_status,
    race_role,
    registration_open_window,
)


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
    organizer: User | None = None,
    started_at: datetime | None = None,
    late_join_window_minutes: int | None = None,
    race_duration_minutes: int | None = None,
    participants: list[Participant] | None = None,
    casters: list[Caster] | None = None,
) -> Race:
    organizer = organizer or _make_user(role=UserRole.ORGANIZER)
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
    race.participants = participants or []
    race.casters = casters or []
    race.seed = None
    return race


def _make_participant(user: User, race: Race, status: ParticipantStatus) -> Participant:
    return Participant(id=uuid4(), race_id=race.id, user_id=user.id, status=status)


def _make_caster(user: User, race: Race) -> Caster:
    return Caster(id=uuid4(), race_id=race.id, user_id=user.id)


def _running_race(*, late_join_open: bool) -> tuple[Race, datetime]:
    """Build a RUNNING race plus a ``now`` value matching the requested window state."""
    started = datetime.now(UTC) - timedelta(minutes=5)
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=started,
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )
    now = started + timedelta(minutes=10) if late_join_open else started + timedelta(minutes=45)
    return race, now


# -- race_role ------------------------------------------------------------------


class TestRaceRole:
    def test_anonymous_returns_none(self):
        race = _make_race(status=RaceStatus.SETUP)
        assert race_role(race, None) is None

    def test_organizer_wins_over_admin(self):
        organizer = _make_user(role=UserRole.ADMIN)
        race = _make_race(status=RaceStatus.SETUP, organizer=organizer)
        assert race_role(race, organizer) == "organizer"

    def test_admin_when_not_organizer(self):
        admin = _make_user(role=UserRole.ADMIN)
        race = _make_race(status=RaceStatus.SETUP)
        assert race_role(race, admin) == "admin"

    def test_caster(self):
        caster_user = _make_user()
        race = _make_race(status=RaceStatus.SETUP)
        race.casters = [_make_caster(caster_user, race)]
        assert race_role(race, caster_user) == "caster"

    def test_participant(self):
        user = _make_user()
        race = _make_race(status=RaceStatus.SETUP)
        race.participants = [_make_participant(user, race, ParticipantStatus.REGISTERED)]
        assert race_role(race, user) == "participant"

    def test_unrelated_authenticated_returns_none(self):
        race = _make_race(status=RaceStatus.SETUP)
        assert race_role(race, _make_user()) is None


# -- small predicates -----------------------------------------------------------


class TestIsActiveParticipantStatus:
    def test_none_is_not_active(self):
        assert is_active_participant_status(None) is False

    def test_finished_and_abandoned_are_not_active(self):
        assert is_active_participant_status(ParticipantStatus.FINISHED) is False
        assert is_active_participant_status(ParticipantStatus.ABANDONED) is False

    def test_registered_ready_playing_are_active(self):
        for s in (
            ParticipantStatus.REGISTERED,
            ParticipantStatus.READY,
            ParticipantStatus.PLAYING,
        ):
            assert is_active_participant_status(s) is True


class TestRegistrationOpenWindow:
    def test_setup_is_always_open(self):
        race = _make_race(status=RaceStatus.SETUP)
        assert registration_open_window(race, datetime.now(UTC)) is True

    def test_finished_is_closed(self):
        race = _make_race(status=RaceStatus.FINISHED)
        assert registration_open_window(race, datetime.now(UTC)) is False

    def test_running_without_late_join_window_is_closed(self):
        race = _make_race(
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
            late_join_window_minutes=None,
        )
        assert registration_open_window(race, datetime.now(UTC)) is False

    def test_running_before_deadline_is_open(self):
        race, now = _running_race(late_join_open=True)
        assert registration_open_window(race, now) is True

    def test_running_after_deadline_is_closed(self):
        race, now = _running_race(late_join_open=False)
        assert registration_open_window(race, now) is False

    def test_running_without_started_at_is_closed(self):
        # Defensive: transient state where status flipped to RUNNING but
        # started_at was not yet committed. Window is treated as closed
        # so spectators do not see public chat by accident.
        race = _make_race(
            status=RaceStatus.RUNNING,
            started_at=None,
            late_join_window_minutes=30,
        )
        assert registration_open_window(race, datetime.now(UTC)) is False


# -- can_read_participants_chat -------------------------------------------------


class TestCanReadParticipantsChat:
    def test_role_yes(self):
        for r in ("organizer", "admin", "caster", "participant"):
            assert can_read_participants_chat(role=r) is True

    def test_no_role(self):
        assert can_read_participants_chat(role=None) is False


# -- can_read_public_chat: matrix from spec lines 60-75 -------------------------


NOW = datetime.now(UTC)


class TestPublicReadSetup:
    """SETUP: locked for everyone."""

    def setup_method(self):
        self.race = _make_race(status=RaceStatus.SETUP)

    def test_participant(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.REGISTERED,
                now=NOW,
            )
            is False
        )

    def test_organizer(self):
        assert (
            can_read_public_chat(self.race, role="organizer", participant_status=None, now=NOW)
            is False
        )

    def test_admin(self):
        assert (
            can_read_public_chat(self.race, role="admin", participant_status=None, now=NOW) is False
        )

    def test_caster(self):
        assert (
            can_read_public_chat(self.race, role="caster", participant_status=None, now=NOW)
            is False
        )

    def test_spectator(self):
        assert can_read_public_chat(self.race, role=None, participant_status=None, now=NOW) is False


class TestPublicReadRunningLateJoinOpen:
    def setup_method(self):
        self.race, self.now = _running_race(late_join_open=True)

    def test_active_participant_locked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.PLAYING,
                now=self.now,
            )
            is False
        )

    def test_registered_participant_locked(self):
        # Late-joiner who just registered: still active, must not see
        # spoilers from the public channel.
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.REGISTERED,
                now=self.now,
            )
            is False
        )

    def test_ready_participant_locked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.READY,
                now=self.now,
            )
            is False
        )

    def test_finished_participant_unlocked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.FINISHED,
                now=self.now,
            )
            is True
        )

    def test_abandoned_participant_unlocked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.ABANDONED,
                now=self.now,
            )
            is True
        )

    def test_spectator_locked(self):
        assert (
            can_read_public_chat(self.race, role=None, participant_status=None, now=self.now)
            is False
        )

    def test_organizer_locked(self):
        # Race role does not unlock public chat: organizers, admins,
        # and casters follow the same spectator rules.
        assert (
            can_read_public_chat(self.race, role="organizer", participant_status=None, now=self.now)
            is False
        )

    def test_admin_locked(self):
        assert (
            can_read_public_chat(self.race, role="admin", participant_status=None, now=self.now)
            is False
        )

    def test_caster_locked(self):
        assert (
            can_read_public_chat(self.race, role="caster", participant_status=None, now=self.now)
            is False
        )


class TestPublicReadRunningLateJoinClosed:
    def setup_method(self):
        self.race, self.now = _running_race(late_join_open=False)

    def test_active_participant_locked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.PLAYING,
                now=self.now,
            )
            is False
        )

    def test_finished_participant_unlocked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.FINISHED,
                now=self.now,
            )
            is True
        )

    def test_spectator_unlocked(self):
        assert (
            can_read_public_chat(self.race, role=None, participant_status=None, now=self.now)
            is True
        )

    def test_organizer_unlocked(self):
        assert (
            can_read_public_chat(self.race, role="organizer", participant_status=None, now=self.now)
            is True
        )


class TestPublicReadRunningNoLateJoinWindow:
    """``RUNNING`` race with ``late_join_window_minutes=None``: behaves
    as if late-join is closed from t=0 (real production case for races
    that do not allow late-join at all)."""

    def setup_method(self):
        self.race = _make_race(
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=1),
            late_join_window_minutes=None,
        )
        self.now = datetime.now(UTC)

    def test_spectator_unlocked(self):
        assert (
            can_read_public_chat(self.race, role=None, participant_status=None, now=self.now)
            is True
        )

    def test_active_participant_locked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.PLAYING,
                now=self.now,
            )
            is False
        )


class TestPublicReadFinished:
    def setup_method(self):
        self.race = _make_race(status=RaceStatus.FINISHED)

    def test_participant_unlocked(self):
        assert (
            can_read_public_chat(
                self.race,
                role="participant",
                participant_status=ParticipantStatus.FINISHED,
                now=NOW,
            )
            is True
        )

    def test_organizer_unlocked(self):
        assert (
            can_read_public_chat(self.race, role="organizer", participant_status=None, now=NOW)
            is True
        )

    def test_anonymous_spectator_unlocked(self):
        assert can_read_public_chat(self.race, role=None, participant_status=None, now=NOW) is True


# -- can_write_public_chat ------------------------------------------------------


class TestCanWritePublicChat:
    def test_anonymous_cannot_write(self):
        race, now = _running_race(late_join_open=False)
        assert (
            can_write_public_chat(race, user_id=None, role=None, participant_status=None, now=now)
            is False
        )

    def test_active_participant_cannot_write_even_with_role(self):
        # Edge case: organizer who is also playing as a participant.
        # They are an active participant, so they cannot write whether
        # the late-join window is open or closed.
        race, now = _running_race(late_join_open=False)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role="organizer",
                participant_status=ParticipantStatus.PLAYING,
                now=now,
            )
            is False
        )

    def test_finished_participant_can_write(self):
        race, now = _running_race(late_join_open=True)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role="participant",
                participant_status=ParticipantStatus.FINISHED,
                now=now,
            )
            is True
        )

    def test_spectator_when_locked_cannot_write(self):
        race, now = _running_race(late_join_open=True)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role=None,
                participant_status=None,
                now=now,
            )
            is False
        )

    def test_spectator_when_unlocked_can_write(self):
        race, now = _running_race(late_join_open=False)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role=None,
                participant_status=None,
                now=now,
            )
            is True
        )

    def test_organizer_can_write_after_late_join_closes(self):
        # Organizers do not bypass the late-join lock: they only gain
        # public-write access once the window has closed (or the race
        # has finished).
        race, now = _running_race(late_join_open=False)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role="organizer",
                participant_status=None,
                now=now,
            )
            is True
        )

    def test_organizer_cannot_write_during_late_join(self):
        race, now = _running_race(late_join_open=True)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role="organizer",
                participant_status=None,
                now=now,
            )
            is False
        )

    def test_finished_race_authenticated_spectator_can_write(self):
        race = _make_race(status=RaceStatus.FINISHED)
        assert (
            can_write_public_chat(
                race,
                user_id=uuid4(),
                role=None,
                participant_status=None,
                now=NOW,
            )
            is True
        )
