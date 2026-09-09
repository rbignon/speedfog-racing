"""Tournament events: slots, scoring, ladder, groups, phase (pure functions).

Everything the event page shows is derived here from loaded rows. Points reuse
the daily formula so a seed scores exactly like a daily; the ladder is the
best of the seeds per mode, summed over the modes; the phase is a function of
the event dates and of the attached races. Nothing is stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Caster, Event, Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.schemas import EVENT_PHASES, EventConfig, EventStage
from speedfog_racing.services.daily_points_service import (
    QualifiedParticipant,
    compute_daily_points,
    rank_key,
)

Phase = Literal["upcoming", "qualifier", "cut", "playoffs", "finished"]


# --- slots ------------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    kind: Literal["qualifier", "stage"]
    key: str
    index: int

    def __str__(self) -> str:
        if self.kind == "qualifier":
            return f"qualifier:{self.key}:{self.index}"
        return f"{self.key}:{self.index}"


def parse_slot(raw: str) -> Slot:
    """Parse ``qualifier:<mode>:<n>`` or ``<stage>:<n>``; raise ValueError otherwise."""
    parts = raw.split(":")
    if len(parts) == 3 and parts[0] == "qualifier":
        key, idx = parts[1], parts[2]
        if not key or not idx.isdigit() or int(idx) < 1:
            raise ValueError(f"malformed slot: {raw!r}")
        return Slot(kind="qualifier", key=key, index=int(idx))
    if len(parts) == 2:
        key, idx = parts[0], parts[1]
        if not key or not idx.isdigit() or int(idx) < 1:
            raise ValueError(f"malformed slot: {raw!r}")
        return Slot(kind="stage", key=key, index=int(idx))
    raise ValueError(f"malformed slot: {raw!r}")


def validate_slot(slot: Slot, config: EventConfig) -> str | None:
    """Return an error message when the slot does not exist in ``config``."""
    if slot.kind == "qualifier":
        if slot.key not in config.mode_keys():
            return f"unknown mode {slot.key!r}"
        if slot.index > config.seeds_per_mode:
            return f"seed index {slot.index} exceeds seeds_per_mode ({config.seeds_per_mode})"
        return None
    stage = config.stage(slot.key)
    if stage is None:
        return f"unknown stage {slot.key!r}"
    if slot.index > stage.races:
        return f"race index {slot.index} exceeds the stage's races ({stage.races})"
    return None


# --- race scores ------------------------------------------------------------


@dataclass(frozen=True)
class RaceScore:
    user_id: UUID
    points: int
    rank: int
    igt_ms: int
    status: ParticipantStatus
    provisional: bool


def score_race(race: Race) -> dict[UUID, RaceScore]:
    """Daily-formula points and ranks for one race, keyed by user.

    Runs with fewer than two zone entries are not qualified and get no score,
    as on dailies. Scores are provisional until the race is FINISHED.
    """
    qualified = [
        QualifiedParticipant(
            participant_id=p.id,
            user_id=p.user_id,
            status=p.status,
            igt_ms=p.igt_ms,
            current_layer=p.current_layer,
        )
        for p in race.participants
        if len(p.zone_history or []) >= 2
    ]
    points = compute_daily_points(qualified)
    ordered = sorted(qualified, key=rank_key)
    provisional = race.status != RaceStatus.FINISHED
    scores: dict[UUID, RaceScore] = {}
    rank = 0
    for i, qp in enumerate(ordered):
        if i == 0 or rank_key(qp) != rank_key(ordered[i - 1]):
            rank = i + 1
        scores[qp.user_id] = RaceScore(
            user_id=qp.user_id,
            points=points[qp.participant_id],
            rank=rank,
            igt_ms=qp.igt_ms,
            status=qp.status,
            provisional=provisional,
        )
    return scores


# --- ladder -----------------------------------------------------------------


@dataclass
class LadderEntry:
    user_id: UUID
    mode_points: dict[str, int | None]
    counted_slots: dict[str, str]
    modes_scored: int
    total: int | None
    partial: int
    igt_total: int
    provisional: bool
    rank: int | None = None


def compute_ladder(modes: list[str], qualifier_races: list[tuple[Slot, Race]]) -> list[LadderEntry]:
    """Best seed per mode, summed over modes; ranked entries first, then unranked."""
    # user -> mode -> (points, igt_ms, provisional, slot)
    best: dict[UUID, dict[str, tuple[int, int, bool, str]]] = {}
    for slot, race in qualifier_races:
        if slot.kind != "qualifier" or slot.key not in modes:
            continue
        for user_id, score in score_race(race).items():
            per_mode = best.setdefault(user_id, {})
            current = per_mode.get(slot.key)
            candidate = (score.points, score.igt_ms, score.provisional, str(slot))
            if (
                current is None
                or candidate[0] > current[0]
                or (candidate[0] == current[0] and candidate[1] < current[1])
            ):
                per_mode[slot.key] = candidate

    entries: list[LadderEntry] = []
    for user_id, per_mode in best.items():
        scored = [per_mode[m] for m in modes if m in per_mode]
        partial = sum(s[0] for s in scored)
        ranked = len(scored) == len(modes)
        entries.append(
            LadderEntry(
                user_id=user_id,
                mode_points={m: (per_mode[m][0] if m in per_mode else None) for m in modes},
                counted_slots={m: per_mode[m][3] for m in modes if m in per_mode},
                modes_scored=len(scored),
                total=partial if ranked else None,
                partial=partial,
                igt_total=sum(s[1] for s in scored),
                provisional=any(s[2] for s in scored),
            )
        )

    ranked_entries = sorted(
        (e for e in entries if e.total is not None), key=lambda e: (-(e.total or 0), e.igt_total)
    )
    rank = 0
    for i, entry in enumerate(ranked_entries):
        previous = ranked_entries[i - 1] if i else None
        if previous is None or (entry.total, entry.igt_total) != (
            previous.total,
            previous.igt_total,
        ):
            rank = i + 1
        entry.rank = rank
    unranked = sorted(
        (e for e in entries if e.total is None), key=lambda e: (-e.modes_scored, -e.partial)
    )
    return ranked_entries + unranked


# --- newcomers --------------------------------------------------------------


def newcomer_flags(
    finished_before: dict[UUID, int], threshold: int, user_ids: Iterable[UUID]
) -> dict[UUID, bool]:
    """A newcomer has strictly fewer than ``threshold`` finished races before the event."""
    return {u: finished_before.get(u, 0) < threshold for u in user_ids}


# --- qualified groups -------------------------------------------------------


@dataclass(frozen=True)
class QualifiedSlot:
    seed: int | None
    user_id: UUID | None
    note: str | None


def compute_qualified(
    ladder: list[LadderEntry], config: EventConfig, newcomers: dict[UUID, bool]
) -> dict[str, list[QualifiedSlot]]:
    """Seeds are positions in the ranked ladder; newcomers come after the last seed."""
    ranked = [e for e in ladder if e.rank is not None]
    groups: dict[str, list[QualifiedSlot]] = {}
    last_seed = 0
    for stage in config.stages:
        if stage.kind != "semi":
            continue
        slots: list[QualifiedSlot] = []
        for seed in stage.seeds or []:
            entry = ranked[seed - 1] if seed - 1 < len(ranked) else None
            slots.append(
                QualifiedSlot(
                    seed=seed,
                    user_id=entry.user_id if entry else None,
                    note=None if entry else "open",
                )
            )
            last_seed = max(last_seed, seed)
        groups[stage.key] = slots
    for stage in config.stages:
        if stage.kind != "newcomers":
            continue
        if stage.size is None:
            # The schema requires a newcomers stage to declare size; this is
            # unreachable for a validated EventConfig, kept as a type-narrowing guard.
            continue
        size = stage.size
        picks = [e for e in ranked[last_seed:] if newcomers.get(e.user_id, False)][:size]
        slots = [QualifiedSlot(seed=e.rank, user_id=e.user_id, note=None) for e in picks]
        while len(slots) < size:
            slots.append(QualifiedSlot(seed=None, user_id=None, note="open"))
        groups[stage.key] = slots
    return groups


# --- stages -----------------------------------------------------------------


@dataclass(frozen=True)
class StageEntry:
    user_id: UUID
    points: int
    igt_total: int
    advances: bool


@dataclass(frozen=True)
class StageResult:
    complete: bool
    entries: list[StageEntry] = field(default_factory=list)


def compute_stage_results(stage: EventStage, races: list[Race], advance: int) -> StageResult:
    """Sum the daily-formula points of a stage's races; ``advance`` best qualify once complete."""
    complete = len(races) == stage.races and all(r.status == RaceStatus.FINISHED for r in races)
    totals: dict[UUID, list[int]] = {}
    for race in races:
        for user_id, score in score_race(race).items():
            bucket = totals.setdefault(user_id, [0, 0])
            bucket[0] += score.points
            bucket[1] += score.igt_ms
    ordered = sorted(totals.items(), key=lambda item: (-item[1][0], item[1][1]))
    entries = [
        StageEntry(user_id=user_id, points=t[0], igt_total=t[1], advances=complete and i < advance)
        for i, (user_id, t) in enumerate(ordered)
    ]
    return StageResult(complete=complete, entries=entries)


@dataclass(frozen=True)
class FieldSlot:
    user_id: UUID | None
    label: str


def final_field(
    final: EventStage, results: dict[str, StageResult], labels: dict[str, str]
) -> list[FieldSlot]:
    """The final's field: the union of advancing runners from ``from``, or a placeholder."""
    assert final.advance is not None, "a final stage always declares advance"
    count = final.advance
    slots: list[FieldSlot] = []
    for key in final.from_ or []:
        result = results.get(key)
        placeholder = f"Top {count} of {labels[key]}"
        if result is not None and result.complete:
            decided = [
                FieldSlot(user_id=e.user_id, label=labels[key])
                for e in result.entries
                if e.advances
            ]
            decided.extend(
                FieldSlot(user_id=None, label=placeholder) for _ in range(count - len(decided))
            )
            slots.extend(decided)
        else:
            slots.extend(FieldSlot(user_id=None, label=placeholder) for _ in range(count))
    return slots


# --- phase ------------------------------------------------------------------


def compute_phase(
    *,
    now: datetime,
    starts_at: datetime,
    qualifier_ends_at: datetime,
    ends_at: datetime,
    first_stage_at: datetime | None,
    last_stage_complete: bool,
    override: str | None,
) -> Phase:
    if override in EVENT_PHASES:
        return override  # type: ignore[return-value]
    if now < starts_at:
        return "upcoming"
    if now < qualifier_ends_at:
        return "qualifier"
    if now >= ends_at or last_stage_complete:
        return "finished"
    if first_stage_at is not None and now < first_stage_at:
        return "cut"
    return "playoffs"


def current_stage_key(config: EventConfig, now: datetime) -> str | None:
    """The stage dated today (UTC), else the next one, else the last one.

    ``now`` must be timezone-aware; a naive datetime makes ``astimezone`` assume the
    local zone (silently wrong) and the ``s.date > now`` comparison raise.
    """
    if not config.stages:
        return None
    today = now.astimezone(UTC).date()
    for stage in config.stages:
        if stage.date.astimezone(UTC).date() == today:
            return stage.key
    upcoming = [s for s in config.stages if s.date > now]
    return upcoming[0].key if upcoming else config.stages[-1].key


# --- timeline ---------------------------------------------------------------


@dataclass(frozen=True)
class TimelineStop:
    key: str
    label: str
    date: datetime
    kind: Literal["announce", "open", "cut", "semi", "newcomers", "final"]


def build_timeline(event: Event, config: EventConfig) -> list[TimelineStop]:
    announced = config.announced_at or (event.starts_at - timedelta(days=7))
    stops = [
        TimelineStop(key="announce", label="Announce", date=announced, kind="announce"),
        TimelineStop(key="open", label="Seeds open", date=event.starts_at, kind="open"),
        TimelineStop(key="cut", label="Cut", date=event.qualifier_ends_at, kind="cut"),
    ]
    stops.extend(
        TimelineStop(key=f"stage:{s.key}", label=s.label, date=s.date, kind=s.kind)
        for s in config.stages
    )
    return stops


# --- loaders ----------------------------------------------------------------


async def load_event(db: AsyncSession, slug: str) -> Event | None:
    """The event and every attached race with what ``race_response`` needs."""
    stmt = (
        select(Event)
        .where(Event.slug == slug)
        .options(
            selectinload(Event.races)
            .selectinload(Race.participants)
            .selectinload(Participant.user),
            selectinload(Event.races).selectinload(Race.casters).selectinload(Caster.user),
            selectinload(Event.races).selectinload(Race.organizer),
            selectinload(Event.races).selectinload(Race.seed),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def count_finished_before(
    db: AsyncSession, user_ids: set[UUID], before: datetime
) -> dict[UUID, int]:
    """Finished race participations per user in races started before ``before``."""
    if not user_ids:
        return {}
    stmt = (
        select(Participant.user_id, func.count())
        .join(Race, Race.id == Participant.race_id)
        .where(
            Participant.user_id.in_(user_ids),
            Participant.status == ParticipantStatus.FINISHED,
            Race.started_at < before,
        )
        .group_by(Participant.user_id)
    )
    return {user_id: count for user_id, count in (await db.execute(stmt)).all()}
