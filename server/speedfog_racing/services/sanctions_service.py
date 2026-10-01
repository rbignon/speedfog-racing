"""Sanctions: disqualifying a race participant, banning an account.

A disqualification moves a participant to the terminal DISQUALIFIED status,
which every result, score and reward path leaves out. The run data stays
untouched so a cancellation can restore the previous status. A ban is an
attribute of the user: it blocks the competitive and social entry points
(see auth.require_not_banned) without touching the role or past results.
See docs/CHEAT_DETECTION.md ("Sanctions").
"""

import uuid
from datetime import datetime

from speedfog_racing.models import Participant, ParticipantStatus


def disqualify(participant: Participant, *, by_id: uuid.UUID, reason: str, now: datetime) -> None:
    """Move ``participant`` to DISQUALIFIED, remembering the status to restore."""
    if participant.status == ParticipantStatus.DISQUALIFIED:
        raise ValueError("already disqualified")
    participant.status_before_disqualification = participant.status
    participant.status = ParticipantStatus.DISQUALIFIED
    participant.disqualified_at = now
    participant.disqualified_by_id = by_id
    participant.disqualification_reason = reason


def reset_participant_progress(participant: Participant) -> None:
    """Back to a fresh entry: what a race reset or a daily reroll does."""
    participant.status = ParticipantStatus.REGISTERED
    participant.current_zone = None
    participant.current_layer = 0
    participant.igt_ms = 0
    participant.death_count = 0
    participant.finished_at = None
    participant.zone_history = None
    participant.last_igt_change_at = None
    # Empty dict, not None: layer_entry_igts is NOT NULL with a {} server_default.
    participant.layer_entry_igts = {}


def cancel_disqualification(participant: Participant, *, race_restarted: bool) -> None:
    """Undo a disqualification.

    ``race_restarted``: the race went back to SETUP (reset, reroll) after the
    disqualification, so the saved status belongs to an attempt that no
    longer exists; the participant then starts over like everyone else.
    """
    if participant.status != ParticipantStatus.DISQUALIFIED:
        raise ValueError("not disqualified")
    if race_restarted or participant.status_before_disqualification is None:
        reset_participant_progress(participant)
    else:
        participant.status = participant.status_before_disqualification
    participant.status_before_disqualification = None
    participant.disqualified_at = None
    participant.disqualified_by_id = None
    participant.disqualification_reason = None
