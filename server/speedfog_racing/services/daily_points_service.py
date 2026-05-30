"""Daily Seed weekly points scoring.

Single source of truth for:
- The per-daily points formula (compute_daily_points).
- The weekly aggregation (compute_weekly_leaderboard).
- The weekly winners selection (compute_weekly_winners).

The points formula is:

    n = qualified participants (zone_history length >= 2)
    r = participant's rank in the intra-daily ordering
    points(r, n) = round(50 * (n - r + 1) / n)

See docs/specs/2026-05-30-daily-weekly-points-design.md for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from speedfog_racing.models import ParticipantStatus


@dataclass(frozen=True)
class QualifiedParticipant:
    """Minimal projection of a Participant used by the points formula.

    Only qualified participants (zone_history length >= 2) should be passed in.
    """

    participant_id: UUID
    user_id: UUID
    status: ParticipantStatus
    igt_ms: int
    zone_history_len: int


def _rank_key(qp: QualifiedParticipant) -> tuple[int, int, int]:
    """Sort key for intra-daily ranking.

    FINISHED first (sorted by igt_ms ascending), then ABANDONED (sorted by
    zone_history_len descending, igt_ms descending as tie-break).
    """
    if qp.status == ParticipantStatus.FINISHED:
        return (0, qp.igt_ms, 0)
    # Abandoned: higher zone_history_len is better -> negate for ascending sort.
    # Within same zone_history_len, higher igt_ms is better -> negate as well.
    return (1, -qp.zone_history_len, -qp.igt_ms)


def compute_daily_points(
    participants: list[QualifiedParticipant],
) -> dict[UUID, int]:
    """Return a mapping participant_id -> points for one closed daily.

    Implements sport-standard tie ranking: equal sort keys share a rank, the
    next rank skips by the size of the tied group (e.g. two tied at the top
    both get rank 1, the next participant is rank 3).
    """
    n = len(participants)
    if n == 0:
        return {}
    ordered = sorted(participants, key=_rank_key)
    points: dict[UUID, int] = {}
    i = 0
    while i < n:
        rank = i + 1
        sig = _rank_key(ordered[i])
        j = i
        while j < n and _rank_key(ordered[j]) == sig:
            points[ordered[j].participant_id] = round(50 * (n - rank + 1) / n)
            j += 1
        i = j
    return points
