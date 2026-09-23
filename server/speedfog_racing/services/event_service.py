"""Tournament events: slots, scoring, ladder, groups, phase (pure functions).

Everything the event page shows is derived here from loaded rows. Points reuse
the daily formula so a seed scores exactly like a daily; the ladder is the
best of the seeds per mode, summed over the modes; the phase is a function of
the event dates and of the attached races. Nothing is stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    Caster,
    Event,
    EventSignup,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
)
from speedfog_racing.schemas import EVENT_PHASES, EventConfig, EventStage, as_aware_utc
from speedfog_racing.services.daily_points_service import (
    QualifiedParticipant,
    compute_daily_points,
    rank_key,
)
from speedfog_racing.services.weapons import BASE_ROW_MODULUS, WEAPONS

Phase = Literal["upcoming", "qualifier", "cut", "playoffs", "finished"]

# While the phase is one of these the event can still be joined: signups are
# taken, and the ladder lists the signed-up runners who have not run yet.
JOINABLE_PHASES: frozenset[Phase] = frozenset({"upcoming", "qualifier"})

# An upcoming event shows who is in only from this many players: below it, the
# opening day is the whole message rather than how few have committed yet.
MIN_UPCOMING_PLAYERS = 10

# The home page band previews this many players as an avatar stack, the
# count carrying the rest.
MAX_PLAYER_PREVIEWS = 8

# An event stays on the bill (home page band, navbar link) this long after its
# end, crowning its champion.
FEATURED_TAIL = timedelta(days=7)


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


def score_race(race: Race, *, settled_only: bool = False) -> dict[UUID, RaceScore]:
    """Daily-formula points and ranks for one race, keyed by user.

    Runs with fewer than two zone entries are not qualified and get no score,
    as on dailies. Scores are provisional until the race is FINISHED. A run
    still in progress ranks like a DNF on its depth so far, unless
    ``settled_only`` keeps only finished or abandoned runs in the field.
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
        and (
            not settled_only
            or p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
        )
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


def compute_ladder(
    modes: list[str],
    qualifier_races: list[tuple[Slot, Race]],
    signed_up: Iterable[UUID] = (),
) -> list[LadderEntry]:
    """Best seed per mode, summed over modes; ranked entries first, then unranked.

    ``signed_up`` are the runners who said they are in, in signup order: the
    ones without a scoring run close the list, without rank, score or counted
    mode. A signed-up runner who scored is already listed through their run.
    """
    # user -> mode -> (points, igt_ms, provisional, slot)
    best: dict[UUID, dict[str, tuple[int, int, bool, str]]] = {}
    for slot, race in qualifier_races:
        if slot.kind != "qualifier" or slot.key not in modes:
            continue
        # A qualifier seed stays open for days: only settled runs score, so a run in
        # progress neither enters the ladder nor moves the other runners' points.
        for user_id, score in score_race(race, settled_only=True).items():
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
    listed = {e.user_id for e in entries}
    signups: list[LadderEntry] = []
    for user_id in signed_up:
        if user_id in listed:
            continue
        listed.add(user_id)
        signups.append(
            LadderEntry(
                user_id=user_id,
                mode_points={m: None for m in modes},
                counted_slots={},
                modes_scored=0,
                total=None,
                partial=0,
                igt_total=0,
                provisional=False,
            )
        )
    return ranked_entries + unranked + signups


# --- newcomers --------------------------------------------------------------


def newcomer_flags(
    finished_before: dict[UUID, int], threshold: int, user_ids: Iterable[UUID]
) -> dict[UUID, bool]:
    """A newcomer has strictly fewer than ``threshold`` finished races before the event."""
    return {u: finished_before.get(u, 0) < threshold for u in user_ids}


# --- qualified groups -------------------------------------------------------


# Display label of a slot nobody holds yet, next to "Seed 4" and "Top 2 of Semi B".
UNDECIDED = "TBD"


@dataclass(frozen=True)
class QualifiedSlot:
    seed: int | None
    user_id: UUID | None
    note: str | None


def compute_qualified(
    ladder: list[LadderEntry], config: EventConfig, newcomers: dict[UUID, bool]
) -> dict[str, list[QualifiedSlot]]:
    """Seeded stages take ladder positions; newcomers come after the largest seed."""
    ranked = [e for e in ladder if e.rank is not None]
    groups: dict[str, list[QualifiedSlot]] = {}
    last_seed = 0
    for stage in config.stages:
        if stage.seeds is None:
            continue
        slots: list[QualifiedSlot] = []
        for seed in stage.seeds or []:
            entry = ranked[seed - 1] if seed - 1 < len(ranked) else None
            slots.append(
                QualifiedSlot(
                    seed=seed,
                    user_id=entry.user_id if entry else None,
                    note=None if entry else UNDECIDED,
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
            slots.append(QualifiedSlot(seed=None, user_id=None, note=UNDECIDED))
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


def fed_field(
    stage: EventStage, config: EventConfig, results: dict[str, StageResult]
) -> list[FieldSlot]:
    """A fed stage's field: each source's advancing runners, or a placeholder per seat."""
    slots: list[FieldSlot] = []
    for key in stage.from_ or []:
        source = config.stage(key)
        assert source is not None and source.advance is not None, (
            "the schema ties every source to an earlier stage with advance"
        )
        count = source.advance
        placeholder = f"Top {count} of {source.label}"
        result = results.get(key)
        if result is not None and result.complete:
            decided = [
                FieldSlot(user_id=e.user_id, label=source.label)
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


# --- signature weapon -------------------------------------------------------


def signature_weapon(histories: Iterable[list[dict[str, Any]] | None]) -> tuple[int, str] | None:
    """The weapon carried the longest over the given zone histories: (base id, name).

    Ticks are summed per weapon over every combo entry (a combo lists the hands'
    weapons, each of which counts); ids outside the catalogue are skipped.
    ``None`` when no history carries a weapon. Ties go to the lower id.
    """
    # Same id normalisation as daily_points_service._aggregate_weapon_combos
    # and api/stats.py; kept inline like them.
    ticks: dict[int, int] = {}
    for history in histories:
        for entry in history or []:
            for combo in entry.get("weapons") or []:
                for raw in combo.get("ids") or []:
                    base = int(raw) - (int(raw) % BASE_ROW_MODULUS)
                    if base in WEAPONS:
                        ticks[base] = ticks.get(base, 0) + int(combo.get("ticks") or 0)
    if not ticks:
        return None
    best = max(ticks.items(), key=lambda kv: (kv[1], -kv[0]))
    return best[0], WEAPONS[best[0]].name


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


# --- event window -----------------------------------------------------------


def event_window(event: Event) -> tuple[datetime, datetime, datetime]:
    """Aware ``(starts_at, qualifier_ends_at, ends_at)``, without touching ``event``.

    SQLite drops the UTC offset on ``DateTime(timezone=True)`` round-trips, so a row
    loaded from a SQLite session comes back naive; reassigning the ORM attributes to
    fix that would dirty the session, and a later autoflush would turn a read-only
    request into a write. Callers get the normalized values as locals instead.
    """
    starts_at = as_aware_utc(event.starts_at)
    qualifier_ends_at = as_aware_utc(event.qualifier_ends_at)
    ends_at = as_aware_utc(event.ends_at)
    assert starts_at is not None
    assert qualifier_ends_at is not None
    assert ends_at is not None
    return starts_at, qualifier_ends_at, ends_at


# --- timeline ---------------------------------------------------------------


@dataclass(frozen=True)
class TimelineStop:
    key: str
    label: str
    date: datetime
    kind: Literal["announce", "open", "cut", "playoffs", "quarter", "semi", "newcomers", "final"]


def announce_date(event: Event, config: EventConfig) -> datetime:
    """When the event was announced: the first timeline stop and the newcomer cut.

    A config with a newcomers' final always dates it (schema rule); without
    one, the default only decides the newcomer tag.
    """
    starts_at, _, _ = event_window(event)
    return config.announced_at or (starts_at - timedelta(days=7))


def build_timeline(event: Event, config: EventConfig) -> list[TimelineStop]:
    starts_at, qualifier_ends_at, _ends_at = event_window(event)
    announced = announce_date(event, config)
    stops = [
        TimelineStop(key="announce", label="Announce", date=announced, kind="announce"),
        TimelineStop(key="open", label="Seeds open", date=starts_at, kind="open"),
        TimelineStop(key="cut", label="Cut", date=qualifier_ends_at, kind="cut"),
    ]
    # Stages scheduled with their players have no date to plot: one stop
    # stands for them, at the cut where the playoffs begin.
    if any(s.date is None for s in config.stages):
        stops.append(
            TimelineStop(key="playoffs", label="Playoffs", date=qualifier_ends_at, kind="playoffs")
        )
    stops.extend(
        TimelineStop(key=f"stage:{s.key}", label=s.label, date=s.date, kind=s.kind)
        for s in config.stages
        if s.date is not None
    )
    return stops


# --- stage dates ------------------------------------------------------------


def race_moment(race: Race) -> datetime | None:
    """When a race is set to start: its schedule, else its actual start (a private race)."""
    return as_aware_utc(race.scheduled_at) or as_aware_utc(race.started_at)


def stage_dates(
    config: EventConfig, stage_races: dict[str, list[tuple[Slot, Race]]]
) -> dict[str, datetime | None]:
    """Each stage's date: the config's when set, else its earliest race, else None."""
    dates: dict[str, datetime | None] = {}
    for stage in config.stages:
        if stage.date is not None:
            dates[stage.key] = stage.date
            continue
        moments = [
            moment
            for _, race in stage_races.get(stage.key, [])
            if (moment := race_moment(race)) is not None
        ]
        dates[stage.key] = min(moments, default=None)
    return dates


def first_config_date(config: EventConfig) -> datetime | None:
    """The earliest date the config fixes, for callers that do not load the races."""
    return min((s.date for s in config.stages if s.date is not None), default=None)


# --- resolved stages --------------------------------------------------------


@dataclass(frozen=True)
class ResolvedStages:
    """An event's attached races sorted into their slots, and what they decide."""

    attached: list[tuple[Slot, Race]]
    # Qualifier races in mode order, then seed index.
    qualifier: list[tuple[Slot, Race]]
    # Each configured stage's races by race index; slots of unknown stages are dropped.
    stage_races: dict[str, list[tuple[Slot, Race]]]
    results: dict[str, StageResult]
    # Each stage's effective date (see ``stage_dates``).
    dates: dict[str, datetime | None]
    phase: Phase


def resolve_stages(event: Event, config: EventConfig, now: datetime) -> ResolvedStages:
    """The event's races sorted into slots, the stage results and the phase at ``now``.

    ``event.races`` must be loaded (``load_event``, ``load_featured_events``).
    """
    starts_at, qualifier_ends_at, ends_at = event_window(event)
    attached: list[tuple[Slot, Race]] = []
    for race in event.races:
        if race.event_slot is None:
            continue
        try:
            attached.append((parse_slot(race.event_slot), race))
        except ValueError:
            continue
    mode_keys = config.mode_keys()
    qualifier = sorted(
        ((s, r) for s, r in attached if s.kind == "qualifier" and s.key in mode_keys),
        key=lambda item: (mode_keys.index(item[0].key), item[0].index),
    )
    stage_races = {
        stage.key: sorted(
            ((s, r) for s, r in attached if s.kind == "stage" and s.key == stage.key),
            key=lambda item: item[0].index,
        )
        for stage in config.stages
    }
    results = {
        stage.key: compute_stage_results(
            stage, [r for _, r in stage_races[stage.key]], stage.advance or 0
        )
        for stage in config.stages
    }
    dates = stage_dates(config, stage_races)
    last = config.stages[-1] if config.stages else None
    phase = compute_phase(
        now=now,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=min((d for d in dates.values() if d is not None), default=None),
        last_stage_complete=results[last.key].complete if last is not None else False,
        override=config.phase_override,
    )
    return ResolvedStages(
        attached=attached,
        qualifier=qualifier,
        stage_races=stage_races,
        results=results,
        dates=dates,
        phase=phase,
    )


def _stage_days(stage: EventStage, resolved: ResolvedStages) -> set[date]:
    """The UTC days a stage is played on: its date's, and each of its races'."""
    moments = [
        resolved.dates.get(stage.key),
        *(race_moment(race) for _, race in resolved.stage_races.get(stage.key, [])),
    ]
    return {m.astimezone(UTC).date() for m in moments if m is not None}


def current_stage_key(config: EventConfig, resolved: ResolvedStages, now: datetime) -> str | None:
    """The stage being played: one with a race running, else one played today (UTC).

    Two stages running at once resolve to the first in bracket order, like the
    live race. Among the stages of the day, the first that has started (any
    attached race not in setup) and is not complete wins; failing that the
    first not complete; else the last of them. ``now`` must be timezone-aware.
    """
    for stage in config.stages:
        if any(r.status == RaceStatus.RUNNING for _, r in resolved.stage_races.get(stage.key, [])):
            return stage.key
    today = now.astimezone(UTC).date()
    todays = [s for s in config.stages if today in _stage_days(s, resolved)]

    def started(stage: EventStage) -> bool:
        return any(r.status != RaceStatus.SETUP for _, r in resolved.stage_races.get(stage.key, []))

    for stage in todays:
        if started(stage) and not resolved.results[stage.key].complete:
            return stage.key
    for stage in todays:
        if not resolved.results[stage.key].complete:
            return stage.key
    return todays[-1].key if todays else None


def next_stage_key(config: EventConfig, resolved: ResolvedStages, now: datetime) -> str | None:
    """The next evening that can honestly be announced, or None.

    The earliest stage ahead of ``now``, not complete, that waits on no stage
    without a date: a final is not "next" while a semi feeding it has none.
    """

    def waits_on_undated(stage: EventStage) -> bool:
        for key in stage.from_ or []:
            source = config.stage(key)
            if source is None:
                continue
            if resolved.dates.get(key) is None and not resolved.results[key].complete:
                return True
            if waits_on_undated(source):
                return True
        return False

    ahead = sorted(
        (
            (moment, stage.key)
            for stage in config.stages
            if (moment := resolved.dates.get(stage.key)) is not None
            and moment > now
            and not resolved.results[stage.key].complete
            and not waits_on_undated(stage)
        ),
        key=lambda item: item[0],
    )
    return ahead[0][1] if ahead else None


# --- loaders ----------------------------------------------------------------


# The seed graphs stay behind: nothing an event endpoint renders reads them,
# and the listing is loaded by every home page visitor.
_EVENT_LOAD_OPTIONS = (
    selectinload(Event.races).selectinload(Race.participants).selectinload(Participant.user),
    selectinload(Event.races).selectinload(Race.casters).selectinload(Caster.user),
    selectinload(Event.races).selectinload(Race.organizer),
    selectinload(Event.races).selectinload(Race.seed).defer(Seed.graph_json),
    selectinload(Event.signups).selectinload(EventSignup.user),
)


async def load_event(db: AsyncSession, slug: str) -> Event | None:
    """The event and every attached race with what ``race_response`` needs."""
    stmt = select(Event).where(Event.slug == slug).options(*_EVENT_LOAD_OPTIONS)
    return (await db.execute(stmt)).scalar_one_or_none()


async def load_featured_events(db: AsyncSession, now: datetime) -> list[Event]:
    """The events on the bill at ``now``, earliest season first, loaded like ``load_event``.

    On the bill means from the announcement (the timeline's first stop) until
    ``FEATURED_TAIL`` after the end. An event whose stored config no longer
    validates is left out: the home page must not break on a document the
    admin tab is repairing. The listing endpoint reorders by phase, which
    needs the attached races.
    """
    stmt = (
        select(Event)
        .where(Event.ends_at > now - FEATURED_TAIL)
        .order_by(Event.starts_at)
        .options(*_EVENT_LOAD_OPTIONS)
    )
    events = (await db.execute(stmt)).scalars().all()
    featured: list[Event] = []
    for event in events:
        try:
            config = EventConfig.model_validate(event.config)
        except ValidationError:
            continue
        if announce_date(event, config) <= now:
            featured.append(event)
    return featured


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
