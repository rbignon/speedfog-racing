"""Chat channel access rules.

Single source of truth for who can read or write each chat channel of a
race. The full matrix lives in
``docs/specs/2026-04-28-public-chat-lock-design.md``.

The helpers come in two shapes:

* ``race_role`` derives the viewer's role from ``(race, user)`` and is
  used at WebSocket auth time.
* The ``can_*`` predicates accept already-derived state (role,
  participant status, current time) so they can be called on every
  broadcast without re-iterating ``race.participants``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from speedfog_racing.models import (
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
    compute_late_join_deadlines,
)

RACE_ROLES = frozenset({"organizer", "admin", "caster", "participant"})


def race_role(race: Race, user: User | None) -> str | None:
    """Resolve a viewer's role within a race.

    Returns ``"organizer"``, ``"admin"``, ``"caster"``, ``"participant"``
    or ``None``. Precedence matches ``RaceSpectatorHandler._auth_and_setup``
    so the role exposed to the client lines up with chat authorization.
    """
    if user is None:
        return None
    if race.organizer_id == user.id:
        return "organizer"
    if user.role == UserRole.ADMIN:
        return "admin"
    if any(c.user_id == user.id for c in race.casters):
        return "caster"
    if any(p.user_id == user.id for p in race.participants):
        return "participant"
    return None


def is_active_participant_status(status: ParticipantStatus | None) -> bool:
    """True when the participant is still racing.

    ``FINISHED`` and ``ABANDONED`` are terminal; every other status
    (including ``REGISTERED``/``READY``/``PLAYING``) is active. ``None``
    means the viewer is not a participant at all.
    """
    if status is None:
        return False
    return status not in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)


def registration_open_window(race: Race, now: datetime) -> bool:
    """True when the race still accepts new participants.

    ``SETUP`` always allows joining. ``RUNNING`` allows it only while a
    late-join window is configured and ``now`` is before the deadline.
    Any other status closes the window.

    ``now`` must be timezone-aware (UTC) because it is compared against
    ``compute_late_join_deadlines``, which yields UTC datetimes.
    """
    if race.status == RaceStatus.SETUP:
        return True
    if race.status != RaceStatus.RUNNING:
        return False
    closes, _ = compute_late_join_deadlines(race)
    if closes is None:
        return False
    return now < closes


def can_read_participants_chat(*, role: str | None) -> bool:
    """True when the viewer may read or post on the participants chat.

    Restricted to authenticated viewers with a race role. Anonymous
    spectators and authenticated viewers without a race role never see
    this channel.
    """
    return role in RACE_ROLES


def can_read_public_chat(
    race: Race,
    *,
    role: str | None,
    participant_status: ParticipantStatus | None,
    now: datetime,
) -> bool:
    """True when the viewer may receive public chat history and broadcasts.

    Locked while spoilers could reach a late-joiner or an active racer;
    unlocked for finished/abandoned participants, after the late-join
    window has closed (for non-active viewers), or once the race is
    ``FINISHED``. Race role does not unlock by itself: organizers,
    admins, and casters follow the same rules as authenticated
    spectators, so they cannot accidentally read spoilers while the
    window is still open.
    """
    if race.status == RaceStatus.FINISHED:
        return True
    if race.status != RaceStatus.RUNNING:
        return False
    if is_active_participant_status(participant_status):
        # Active racer: locked until they finish or abandon, regardless
        # of late-join state or race role.
        return False
    if participant_status is not None:
        # Finished or abandoned participant: unlocked even while the
        # late-join window is still open.
        return True
    # Non-participant viewer (spectator or any race role not also
    # playing): unlocked only once the late-join window has closed.
    return not registration_open_window(race, now)


def can_write_public_chat(
    race: Race,
    *,
    user_id: UUID | None,
    role: str | None,
    participant_status: ParticipantStatus | None,
    now: datetime,
) -> bool:
    """True when the viewer may post on the public chat.

    Writers must be authenticated, must satisfy
    ``can_read_public_chat``, and must not be an active participant.
    """
    if user_id is None:
        return False
    if not can_read_public_chat(race, role=role, participant_status=participant_status, now=now):
        return False
    if is_active_participant_status(participant_status):
        return False
    return True
