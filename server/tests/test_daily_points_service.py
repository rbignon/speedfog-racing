"""Unit tests for daily_points_service pure helpers."""

from __future__ import annotations

from uuid import UUID, uuid4

from speedfog_racing.models import ParticipantStatus
from speedfog_racing.services.daily_points_service import (
    QualifiedParticipant,
    compute_daily_points,
)


def _qp(
    *,
    user_id: UUID | None = None,
    status: ParticipantStatus,
    igt_ms: int,
    zone_history_len: int,
) -> QualifiedParticipant:
    return QualifiedParticipant(
        participant_id=uuid4(),
        user_id=user_id or uuid4(),
        status=status,
        igt_ms=igt_ms,
        zone_history_len=zone_history_len,
    )


def test_single_finisher_gets_50_points():
    qp = _qp(status=ParticipantStatus.FINISHED, igt_ms=1500, zone_history_len=10)
    points = compute_daily_points([qp])
    assert points[qp.participant_id] == 50


def test_five_finishers_linear_ladder():
    qps = [
        _qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i, zone_history_len=10)
        for i in range(5)
    ]
    points = compute_daily_points(qps)
    expected = [50, 40, 30, 20, 10]
    for qp, exp in zip(qps, expected, strict=True):
        assert points[qp.participant_id] == exp


def test_fifty_finishers_last_gets_1_point():
    qps = [
        _qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i, zone_history_len=10)
        for i in range(50)
    ]
    points = compute_daily_points(qps)
    assert points[qps[0].participant_id] == 50
    assert points[qps[-1].participant_id] == 1


def test_finished_then_abandoned_ordering():
    finisher = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=15)
    further_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=900, zone_history_len=12)
    earlier_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=500, zone_history_len=5)
    points = compute_daily_points([finisher, further_abandon, earlier_abandon])
    # n = 3. Ranks: finisher=1, further_abandon=2, earlier_abandon=3.
    assert points[finisher.participant_id] == 50  # round(50 * 3/3) = 50
    assert points[further_abandon.participant_id] == 33  # round(50 * 2/3) = 33
    assert points[earlier_abandon.participant_id] == 17  # round(50 * 1/3) = 17


def test_abandoned_tiebreak_uses_zone_history_then_igt():
    a = _qp(status=ParticipantStatus.ABANDONED, igt_ms=800, zone_history_len=10)
    # same zone_history_len as a, higher igt -> ranks above a
    b = _qp(status=ParticipantStatus.ABANDONED, igt_ms=1200, zone_history_len=10)
    # fewer zones -> last
    c = _qp(status=ParticipantStatus.ABANDONED, igt_ms=900, zone_history_len=5)
    points = compute_daily_points([a, b, c])
    # n = 3. Ranks: b=1, a=2, c=3.
    assert points[b.participant_id] == 50
    assert points[a.participant_id] == 33
    assert points[c.participant_id] == 17


def test_strict_igt_tie_uses_sport_convention():
    """Two finishers tied at the same IGT share rank 1, next rank skips to 3."""
    a = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=10)
    b = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=10)
    c = _qp(status=ParticipantStatus.FINISHED, igt_ms=2000, zone_history_len=10)
    points = compute_daily_points([a, b, c])
    # n = 3. Ranks: a=1, b=1, c=3.
    assert points[a.participant_id] == 50
    assert points[b.participant_id] == 50
    assert points[c.participant_id] == 17  # round(50 * 1/3) = 17


def test_empty_input_returns_empty_dict():
    assert compute_daily_points([]) == {}
