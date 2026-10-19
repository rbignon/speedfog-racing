"""Tournament events: slots, scoring, ladder, groups, phase (pure functions).

Everything the event page shows is derived here from loaded rows. Qualifier
points reuse the daily formula so a seed scores exactly like a daily, while
playoff races score on the event's own table; the ladder is the best of the
seeds per mode, summed over the modes; the phase is a function of the event
dates and of the attached races. Nothing is stored, except the in-game
deadline a playoff race's finishes set (``update_playoff_cutoff``).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import ColumnElement, func, or_, select, update
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
    User,
)
from speedfog_racing.schemas import (
    EVENT_PHASES,
    EventBracket,
    EventConfig,
    EventShowcase,
    EventStage,
    as_aware_utc,
)
from speedfog_racing.services.daily_points_service import (
    QualifiedParticipant,
    compute_daily_points,
    daily_points_for_race,
    rank_key,
)
from speedfog_racing.services.weapons import BASE_ROW_MODULUS, WEAPONS

logger = logging.getLogger(__name__)

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
    stage = config.stage(slot.key) or config.showcase(slot.key)
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
    # The time the run played, as the seed card shows it.
    igt_ms: int
    # The time it ranks on: a DNF's first arrival on its deepest layer.
    ranking_igt_ms: int
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
            layer_entry_igt=(p.layer_entry_igts or {}).get(str(p.current_layer)),
        )
        for p in race.participants
        if len(p.zone_history or []) >= 2
        and p.status != ParticipantStatus.DISQUALIFIED
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
            ranking_igt_ms=qp.ranking_igt_ms,
            status=qp.status,
            provisional=provisional,
        )
    return scores


def leaderboard_points(race: Race) -> dict[UUID, int]:
    """Map participant_id -> points shown on the race leaderboard's rows.

    A closed daily scores its whole field (``daily_points_for_race``). An event
    qualifier scores each run as soon as it settles, with the points the seed
    card and the ladder show: a run in progress shows none, and the settled
    runs' points move while the seed stays open. Any other race shows none.
    """
    if race.is_event_qualifier:
        scores = score_race(race, settled_only=True)
        return {p.id: scores[p.user_id].points for p in race.participants if p.user_id in scores}
    return daily_points_for_race(race)


# --- ladder -----------------------------------------------------------------


@dataclass
class LadderEntry:
    user_id: UUID
    mode_points: dict[str, int | None]
    counted_slots: dict[str, str]
    modes_scored: int
    total: int | None
    partial: int
    # Counted seeds the runner finished, the first tie-break after points.
    finished_seeds: int
    igt_total: int
    provisional: bool
    rank: int | None = None
    withdrawn: bool = False


def compute_ladder(
    modes: list[str],
    qualifier_races: list[tuple[Slot, Race]],
    signed_up: Iterable[UUID] = (),
    struck: Collection[UUID] = (),
) -> list[LadderEntry]:
    """Best seed per mode, summed over modes; ranked entries first, then unranked.

    ``signed_up`` are the runners who said they are in, in signup order: the
    ones without a scoring run close the list, without rank, score or counted
    mode. A signed-up runner who scored is already listed through their run.

    ``struck`` are the runners who withdrew before the draw locked: they keep
    their place in the list, unranked and flagged ``withdrawn``, and the others
    are ranked as if they were absent, so the numbering carries on past them.
    """
    # user -> mode -> (points, finished, ranking igt_ms, provisional, slot)
    best: dict[UUID, dict[str, tuple[int, bool, int, bool, str]]] = {}
    for slot, race in qualifier_races:
        if slot.kind != "qualifier" or slot.key not in modes:
            continue
        # A qualifier seed stays open for days: only settled runs score, so a run in
        # progress neither enters the ladder nor moves the other runners' points.
        for user_id, score in score_race(race, settled_only=True).items():
            per_mode = best.setdefault(user_id, {})
            current = per_mode.get(slot.key)
            finished = score.status == ParticipantStatus.FINISHED
            candidate = (
                score.points,
                finished,
                score.ranking_igt_ms,
                score.provisional,
                str(slot),
            )
            # More points, then a finish over a DNF, then the lower time: the
            # order the ladder itself breaks ties in.
            if current is None or (candidate[0], candidate[1], -candidate[2]) > (
                current[0],
                current[1],
                -current[2],
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
                counted_slots={m: per_mode[m][4] for m in modes if m in per_mode},
                modes_scored=len(scored),
                total=partial if ranked else None,
                partial=partial,
                finished_seeds=sum(s[1] for s in scored),
                igt_total=sum(s[2] for s in scored),
                provisional=any(s[3] for s in scored),
            )
        )

    # Ties on points go to the runner with more counted seeds finished, then to
    # the lower summed time (a DNF's being its arrival on its deepest layer).
    ranked_entries = sorted(
        (e for e in entries if e.total is not None),
        key=lambda e: (-(e.total or 0), -e.finished_seeds, e.igt_total),
    )
    struck_ids = set(struck)
    rank = 0
    counted: list[LadderEntry] = []
    for entry in ranked_entries:
        if entry.user_id in struck_ids:
            entry.withdrawn = True
            continue
        previous = counted[-1] if counted else None
        if previous is None or (entry.total, entry.finished_seeds, entry.igt_total) != (
            previous.total,
            previous.finished_seeds,
            previous.igt_total,
        ):
            rank = len(counted) + 1
        entry.rank = rank
        counted.append(entry)
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
                finished_seeds=0,
                igt_total=0,
                provisional=False,
            )
        )
    for entry in (*unranked, *signups):
        entry.withdrawn = entry.user_id in struck_ids
    return ranked_entries + unranked + signups


# --- newcomers --------------------------------------------------------------


def newcomer_flags(
    finished_before: dict[UUID, int], threshold: int, user_ids: Iterable[UUID]
) -> dict[UUID, bool]:
    """A newcomer has strictly fewer than ``threshold`` finished races before the event."""
    return {u: finished_before.get(u, 0) < threshold for u in user_ids}


# --- qualified groups -------------------------------------------------------


# Display label of a slot nobody holds yet, next to "Seed 4" and "1st of Semi B".
UNDECIDED = "TBD"
# Display label of a seat nobody can hold any more: the ladder is final and no
# runner is left on it to seat.
NO_RUNNER = "No runner"


@dataclass(frozen=True)
class QualifiedSlot:
    seed: int | None
    user_id: UUID | None
    note: str | None
    # Withdrew after the draw locked: the seat stays theirs, nobody replaces them.
    forfeited: bool = False


def resolve_withdrawn(names: Sequence[str], users: Mapping[UUID, User]) -> list[UUID]:
    """The ids behind ``names``, in their order, matched case-insensitively.

    A name matching none of ``users`` is skipped: a runner off the ladder holds
    no seat and can be nobody's replacement.
    """
    by_name = {user.twitch_username.lower(): user_id for user_id, user in users.items()}
    return [user_id for name in names if (user_id := by_name.get(name.strip().lower())) is not None]


def resolve_caster_languages(
    languages: Mapping[str, str], races: Iterable[Race]
) -> dict[UUID, str]:
    """``languages`` keyed by the user id of each caster attached to ``races``.

    Names match Twitch usernames case-insensitively; a name casting none of
    ``races`` is left out.
    """
    by_name = {name.strip().lower(): code for name, code in languages.items()}
    resolved: dict[UUID, str] = {}
    for race in races:
        for caster in race.casters:
            code = by_name.get(caster.user.twitch_username.lower())
            if code is not None:
                resolved[caster.user_id] = code
    return resolved


def compute_qualified(
    ladder: list[LadderEntry],
    config: EventConfig,
    newcomers: dict[UUID, bool],
    ladder_final: bool = False,
    forfeits: Collection[UUID] = (),
) -> dict[str, list[QualifiedSlot]]:
    """Each bracket seats its seeded stages from its own pool, in bracket order.

    A bracket's pool is the ranked ladder (the runners who withdrew before the
    lock are unranked there, see ``compute_ladder``) filtered by its entry
    (everyone, or the newcomers), less every runner an earlier bracket drew;
    its stages' ``seeds`` index that pool, and a seat shows its runner's
    position on the ranked ladder. ``forfeits`` withdrew after the lock: they
    keep their seat, flagged, and nobody replaces them. A seat nobody can fill
    reads ``UNDECIDED`` while the ladder can still move, ``NO_RUNNER`` once it
    is final; past the end of a provisional ladder it keeps its seed number
    only in a bracket drawing from everyone, where that number is the ladder
    position it waits on.
    """
    ranked = [e for e in ladder if e.rank is not None]
    position = {e.user_id: i for i, e in enumerate(ranked, start=1)}
    forfeit_ids = set(forfeits)
    empty = NO_RUNNER if ladder_final else UNDECIDED
    groups: dict[str, list[QualifiedSlot]] = {}
    # Everyone a bracket has seated so far.
    drawn: set[UUID] = set()
    for bracket in config.brackets:
        pool = [
            e
            for e in ranked
            if e.user_id not in drawn
            and (bracket.entry == "all" or newcomers.get(e.user_id, False))
        ]
        numbered = bracket.entry == "all"
        for stage in bracket.stages:
            if stage.seeds is None:
                continue
            slots: list[QualifiedSlot] = []
            for seed in stage.seeds:
                entry = pool[seed - 1] if seed - 1 < len(pool) else None
                if entry is None:
                    slots.append(
                        QualifiedSlot(seed=seed if numbered else None, user_id=None, note=empty)
                    )
                    continue
                slots.append(
                    QualifiedSlot(
                        seed=position[entry.user_id],
                        user_id=entry.user_id,
                        note=None,
                        forfeited=entry.user_id in forfeit_ids,
                    )
                )
                drawn.add(entry.user_id)
            groups[stage.key] = slots
    return groups


def slot_label(slot: QualifiedSlot) -> str:
    """A qualified seat's field label: "Seed N", else its note."""
    if slot.note == NO_RUNNER:
        return NO_RUNNER
    if slot.seed is not None:
        return f"Seed {slot.seed}"
    return slot.note or UNDECIDED


def bracket_draw(
    config: EventConfig, qualified: Mapping[str, list[QualifiedSlot]]
) -> list[tuple[EventBracket, list[UUID]]]:
    """Each bracket with the runners ``compute_qualified`` seated in it, best seed first.

    Seeds are ladder positions. A seat nobody holds, or held by a forfeit, is
    left out: a bracket nobody holds a seat in yet comes with an empty list.
    """
    draw: list[tuple[EventBracket, list[UUID]]] = []
    for bracket in config.brackets:
        seats = sorted(
            (slot for stage in bracket.stages for slot in qualified.get(stage.key, [])),
            key=lambda slot: slot.seed or 0,
        )
        draw.append(
            (
                bracket,
                [s.user_id for s in seats if s.user_id is not None and not s.forfeited],
            )
        )
    return draw


def apply_walkovers(
    config: EventConfig,
    resolved: ResolvedStages,
    qualified: Mapping[str, list[QualifiedSlot]],
    forfeits: Collection[UUID] = (),
) -> set[str]:
    """Complete in ``resolved.results`` every stage that needs no match; name them.

    A stage other than a final, with no race attached, whose field is settled
    (every seat held or past the end of a final ladder; every source
    complete), is short of runners (forfeits or empty seats) and keeps no
    more of them than it sends on, is complete: they all advance, without
    points, by seed (a fed stage keeps its field's order). A stage whose
    whole field advances by design still plays: nobody is missing. Stages run in
    bracket order, so a stage completed here feeds the next. Call it right after
    the draw, before anything reads stage completeness (the current and next
    stage, the fed fields).
    """
    out = set(forfeits)
    walkovers: set[str] = set()
    for stage in config.stages:
        if stage.kind == "final" or stage.advance is None or resolved.stage_races[stage.key]:
            continue
        if stage.seeds is not None:
            slots = qualified.get(stage.key, [])
            if any(s.user_id is None and s.note != NO_RUNNER for s in slots):
                continue
            seats = len(slots)
            present = [
                s.user_id
                for s in sorted(slots, key=lambda s: s.seed or 0)
                if s.user_id is not None and s.user_id not in out
            ]
        else:
            if not all(resolved.results[key].complete for key in stage.source_keys):
                continue
            fed = fed_field(stage, config, resolved.results)
            seats = len(fed)
            present = [s.user_id for s in fed if s.user_id is not None and s.user_id not in out]
        if len(present) >= seats or len(present) > stage.advance:
            continue
        resolved.results[stage.key] = StageResult(
            complete=True,
            entries=[
                StageEntry(user_id=user_id, points=0, igt_total=0, advances=True)
                for user_id in present
            ],
        )
        walkovers.add(stage.key)
    return walkovers


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


@dataclass(frozen=True)
class PlayoffScore:
    points: int
    # The in-game time the stage's tie-break sums, a DNF's included.
    igt_ms: int
    # The layer reached, the tie-break after in-game time.
    depth: int


def playoff_deadline_ms(race: Race, config: EventConfig) -> int | None:
    """The in-game time a playoff race's runs must finish by, ``None`` until one has.

    The race's best finished time plus ``config.playoff_cutoff_minutes``: a
    later, faster finish brings it down, so it only ever goes down.
    """
    best = min(
        (p.igt_ms for p in race.participants if p.status == ParticipantStatus.FINISHED),
        default=None,
    )
    return None if best is None else best + config.playoff_cutoff_minutes * 60_000


def score_playoff_race(race: Race, config: EventConfig) -> dict[UUID, PlayoffScore]:
    """Playoff score per user for one stage or showcase race.

    Only the runs finished by the race's deadline (``playoff_deadline_ms``)
    score: ``config.playoff_points`` by in-game time, equal times sharing a
    rank, the table's last value for every finisher past it. Every other
    runner of the race, a run still in progress and a finish past the
    deadline included, is a DNF on 0 points whose tie-break time is the
    deadline, however early the run stopped. A disqualified runner is such a
    DNF with no depth either, so the tie-break never puts them ahead of
    anyone. A race nobody has finished, one still in setup included, lists
    nobody.
    """
    deadline = playoff_deadline_ms(race, config)
    if deadline is None:
        return {}
    finishers = sorted(
        (
            p
            for p in race.participants
            if p.status == ParticipantStatus.FINISHED and p.igt_ms <= deadline
        ),
        key=lambda p: p.igt_ms,
    )
    table = config.playoff_points
    scores: dict[UUID, PlayoffScore] = {}
    rank = 0
    for i, p in enumerate(finishers):
        if i == 0 or p.igt_ms != finishers[i - 1].igt_ms:
            rank = i
        scores[p.user_id] = PlayoffScore(
            table[min(rank, len(table) - 1)], p.igt_ms, p.current_layer
        )
    for p in race.participants:
        depth = 0 if p.status == ParticipantStatus.DISQUALIFIED else p.current_layer
        scores.setdefault(p.user_id, PlayoffScore(0, deadline, depth))
    return scores


def compute_stage_results(
    stage: EventStage | EventShowcase, races: list[Race], advance: int, config: EventConfig
) -> StageResult:
    """Sum the playoff points of a stage's races; ``advance`` best qualify once complete.

    Ties on points go to the lower summed in-game time, then to the deeper
    summed reach (two runners who finished nothing all evening), then to the
    user id: an arbitrary but fixed order, so the page never flips between
    loads.
    """
    complete = len(races) == stage.races and all(r.status == RaceStatus.FINISHED for r in races)
    # user -> [points, igt_ms, depth], each summed over the races
    totals: dict[UUID, list[int]] = {}
    for race in races:
        for user_id, score in score_playoff_race(race, config).items():
            bucket = totals.setdefault(user_id, [0, 0, 0])
            bucket[0] += score.points
            bucket[1] += score.igt_ms
            bucket[2] += score.depth
    ordered = sorted(
        totals.items(), key=lambda item: (-item[1][0], item[1][1], -item[1][2], item[0])
    )
    entries = [
        StageEntry(user_id=user_id, points=t[0], igt_total=t[1], advances=complete and i < advance)
        for i, (user_id, t) in enumerate(ordered)
    ]
    return StageResult(complete=complete, entries=entries)


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


@dataclass(frozen=True)
class FieldSlot:
    user_id: UUID | None
    label: str
    # A fed seat: the stage it comes from and the place it takes there.
    source: str | None = None
    place: int | None = None


def fed_field(
    stage: EventStage, config: EventConfig, results: dict[str, StageResult]
) -> list[FieldSlot]:
    """A fed stage's field, one seat per place it takes ("1st of Group A").

    A whole source (a stage key alone in ``from``) gives all its places, in
    order. Once the source is complete, a seat holds the runner who finished
    in that place among its advancing runners, or reads ``NO_RUNNER`` when
    it sent fewer; until then it reads its label.
    """
    slots: list[FieldSlot] = []
    for key, place in stage.sources:
        source = config.stage(key)
        assert source is not None and source.advance is not None, (
            "the schema ties every source to an earlier stage with advance"
        )
        places = [place] if place is not None else list(range(1, source.advance + 1))
        result = results.get(key)
        advancing = (
            [e.user_id for e in result.entries if e.advances]
            if result is not None and result.complete
            else None
        )
        for p in places:
            label = f"{_ordinal(p)} of {source.label}"
            if advancing is None:
                slots.append(FieldSlot(user_id=None, label=label, source=key, place=p))
            elif p <= len(advancing):
                slots.append(FieldSlot(user_id=advancing[p - 1], label=label, source=key, place=p))
            else:
                slots.append(FieldSlot(user_id=None, label=NO_RUNNER, source=key, place=p))
    return slots


def eliminated_runners(
    config: EventConfig,
    results: dict[str, StageResult],
    qualified: Mapping[str, list[QualifiedSlot]],
) -> set[UUID]:
    """The runners a complete stage knocked out of their bracket.

    A complete stage that sends runners on knocks out the rest of its field, a
    seat that never raced included; a complete final knocks out all but its
    winner. A stage still being played knocks out nobody yet, and neither does
    a closing stage that is no final: it crowns nobody. ``results`` must hold
    the walkovers (``apply_walkovers``).
    """
    out: set[UUID] = set()
    for stage in config.stages:
        result = results[stage.key]
        if not result.complete:
            continue
        if stage.kind == "final":
            kept = {result.entries[0].user_id} if result.entries else set()
        elif stage.advance is not None:
            kept = {e.user_id for e in result.entries if e.advances}
        else:
            continue
        if stage.from_:
            seated = [slot.user_id for slot in fed_field(stage, config, results)]
        else:
            seated = [slot.user_id for slot in qualified.get(stage.key, [])]
        out.update(user_id for user_id in seated if user_id is not None and user_id not in kept)
    return out


def showcase_field(showcase: EventShowcase, races: list[Race]) -> list[FieldSlot]:
    """A showcase's field: whoever joined one of its races, by username."""
    users = {p.user_id: p.user for race in races for p in race.participants}
    ordered = sorted(users.items(), key=lambda item: item[1].twitch_username)
    return [FieldSlot(user_id=user_id, label=showcase.label) for user_id, _ in ordered]


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
    brackets_complete: bool,
    override: str | None,
) -> Phase:
    if override in EVENT_PHASES:
        return override  # type: ignore[return-value]
    if now < starts_at:
        return "upcoming"
    if now < qualifier_ends_at:
        return "qualifier"
    if now >= ends_at or brackets_complete:
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
    kind: Literal["announce", "open", "cut", "playoffs", "round", "quarter", "semi", "final"]


def announce_date(event: Event, config: EventConfig) -> datetime:
    """When the event was announced: the first timeline stop and the newcomer cut.

    A config with a newcomers bracket always dates it (schema rule); without
    one, the default only decides the newcomer tag.
    """
    starts_at, _, _ = event_window(event)
    return config.announced_at or (starts_at - timedelta(days=7))


def build_timeline(
    event: Event, config: EventConfig, dates: Mapping[str, datetime | None]
) -> list[TimelineStop]:
    """The announcement, the opening, the cut, then the playoffs in date order.

    ``dates`` are the stages' effective dates (``ResolvedStages.dates``), so a
    stage the config dates by its day alone sits at its race's time once one is
    scheduled. Every bracket's dated stages get a stop each; the stages
    scheduled with their players (no config date), whatever their bracket,
    fold into one ``playoffs`` stop. That stop is dated by the earliest match
    scheduled among them, kept at or after its floor (the cut, and every dated
    stage listed before its bracket's first undated one) and at or before its
    ceiling (the earliest dated stage listed after its bracket's first undated
    one), the floor winning should they cross; with no match scheduled yet it
    stands on its floor. Stops run in date order; on a tie the playoffs stop
    comes after its floor's stops and before the others, so the rail never
    runs backwards.
    """
    starts_at, qualifier_ends_at, _ends_at = event_window(event)
    announced = announce_date(event, config)
    stops = [
        TimelineStop(key="announce", label="Announce", date=announced, kind="announce"),
        TimelineStop(key="open", label="Seeds open", date=starts_at, kind="open"),
        TimelineStop(key="cut", label="Cut", date=qualifier_ends_at, kind="cut"),
    ]
    # (date, tie, stop): on the same date, tie 0 runs before the playoffs stop
    # (tie 1), tie 2 after it; the sort is stable, so bracket and stage order
    # settle the rest.
    ordered: list[tuple[datetime, int, TimelineStop]] = []
    floor = qualifier_ends_at
    ceiling: datetime | None = None
    for bracket in config.brackets:
        first_undated = next((i for i, s in enumerate(bracket.stages) if s.date is None), None)
        for i, s in enumerate(bracket.stages):
            if s.moment is None:
                continue
            when = dates.get(s.key) or s.moment
            after = first_undated is not None and i > first_undated
            ordered.append(
                (
                    when,
                    2 if after else 0,
                    TimelineStop(key=f"stage:{s.key}", label=s.label, date=when, kind=s.kind),
                )
            )
            if first_undated is None:
                continue
            if after:
                ceiling = when if ceiling is None else min(ceiling, when)
            else:
                floor = max(floor, when)
    undated = [s for s in config.stages if s.date is None]
    if undated:
        scheduled = [at for s in undated if (at := dates.get(s.key)) is not None]
        moment = min(scheduled) if scheduled else floor
        if ceiling is not None:
            moment = min(moment, ceiling)
        moment = max(moment, floor)
        ordered.append(
            (
                moment,
                1,
                TimelineStop(key="playoffs", label="Playoffs", date=moment, kind="playoffs"),
            )
        )
    ordered.sort(key=lambda item: (item[0], item[1]))
    return stops + [stop for _, _, stop in ordered]


# --- stage dates ------------------------------------------------------------


def race_moment(race: Race) -> datetime | None:
    """When a race is set to start: its schedule, else its actual start (a private race)."""
    return as_aware_utc(race.scheduled_at) or as_aware_utc(race.started_at)


def stage_dates(
    stages: Sequence[EventStage | EventShowcase], stage_races: dict[str, list[tuple[Slot, Race]]]
) -> dict[str, datetime | None]:
    """Each stage's date: the config's when it has a time, else its earliest race,
    else the config's day (at noon UTC), else None."""
    dates: dict[str, datetime | None] = {}
    for stage in stages:
        if isinstance(stage.date, datetime):
            dates[stage.key] = stage.date
            continue
        moments = [
            moment
            for _, race in stage_races.get(stage.key, [])
            if (moment := race_moment(race)) is not None
        ]
        dates[stage.key] = min(moments, default=stage.moment)
    return dates


def stage_time_set(stage: EventStage | EventShowcase, races: list[tuple[Slot, Race]]) -> bool:
    """False while the stage's date is a config day none of its races has timed yet."""
    if stage.date is None or isinstance(stage.date, datetime):
        return True
    return any(race_moment(race) is not None for _, race in races)


def first_config_date(config: EventConfig) -> datetime | None:
    """The earliest date the config fixes, for callers that do not load the races."""
    return min((s.moment for s in config.stages if s.moment is not None), default=None)


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
    # The showcases, resolved like stages, apart so nothing the bracket drives sees them.
    showcase_races: dict[str, list[tuple[Slot, Race]]]
    showcase_results: dict[str, StageResult]
    showcase_dates: dict[str, datetime | None]

    @property
    def showcase_race_ids(self) -> set[UUID]:
        """The races of the showcases, attached to the event but entering nobody in it.

        Anything counting the event's players off ``event.races`` must skip them.
        """
        return {race.id for races in self.showcase_races.values() for _, race in races}


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

    def races_of(key: str) -> list[tuple[Slot, Race]]:
        return sorted(
            ((s, r) for s, r in attached if s.kind == "stage" and s.key == key),
            key=lambda item: item[0].index,
        )

    stage_races = {stage.key: races_of(stage.key) for stage in config.stages}
    showcase_races = {showcase.key: races_of(showcase.key) for showcase in config.showcases}
    results = {
        stage.key: compute_stage_results(
            stage, [r for _, r in stage_races[stage.key]], stage.advance or 0, config
        )
        for stage in config.stages
    }
    dates = stage_dates(config.stages, stage_races)
    # The event is over once every bracket is: its final, or its last stage.
    closing = [bracket.closing_stage() for bracket in config.brackets]
    phase = compute_phase(
        now=now,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=min((d for d in dates.values() if d is not None), default=None),
        brackets_complete=bool(closing) and all(results[s.key].complete for s in closing),
        override=config.phase_override,
    )
    return ResolvedStages(
        attached=attached,
        qualifier=qualifier,
        stage_races=stage_races,
        results=results,
        dates=dates,
        phase=phase,
        showcase_races=showcase_races,
        showcase_results={
            s.key: compute_stage_results(s, [r for _, r in showcase_races[s.key]], 0, config)
            for s in config.showcases
        },
        showcase_dates=stage_dates(config.showcases, showcase_races),
    )


def _stage_days(stage: EventStage, resolved: ResolvedStages) -> set[date]:
    """The UTC days a stage is played on: its date's, and each of its races'."""
    moments = [
        resolved.dates.get(stage.key),
        *(race_moment(race) for _, race in resolved.stage_races.get(stage.key, [])),
    ]
    return {m.astimezone(UTC).date() for m in moments if m is not None}


def current_stage_race(races: list[tuple[Slot, Race]], expected: int) -> tuple[Race | None, bool]:
    """The race of a stage a cast scene should show, and whether the stage is done.

    A running race holds the scene. Otherwise the next race, the lowest slot not
    finished, takes it once its seeds are out, so the scenes move on while its
    runners get ready (download, character, weapons) rather than at its start,
    and a race reset to setup keeps it. Only the next race counts: seeds released
    early for a later slot (an organizer checking a seed) neither skip it nor
    pull the scenes ahead and back. Failing that, the latest finished slot keeps
    the scene, so a finished race stays up until the next one's seeds are out;
    before any of that it is the first slot. ``done`` once every slot
    1..``expected`` has a finished race.
    """
    if not races:
        return None, False
    ordered = sorted(races, key=lambda item: item[0].index)
    finished = {slot.index for slot, race in ordered if race.status == RaceStatus.FINISHED}
    done = all(i in finished for i in range(1, expected + 1))
    running = [race for _, race in ordered if race.status == RaceStatus.RUNNING]
    if running:
        return running[-1], done
    upcoming = [race for _, race in ordered if race.status == RaceStatus.SETUP]
    if upcoming and upcoming[0].seeds_released_at is not None:
        return upcoming[0], done
    ended = [race for _, race in ordered if race.status == RaceStatus.FINISHED]
    return (ended[-1] if ended else ordered[0][1]), done


def current_stage_key(
    config: EventConfig,
    resolved: ResolvedStages,
    now: datetime,
    stages: Sequence[EventStage] | None = None,
) -> str | None:
    """The stage being played: one with a race running, else one played today (UTC).

    Two stages running at once resolve to the first in bracket order, like the
    live race. Among the stages of the day, the first that has started (any
    attached race not in setup) and is not complete wins; failing that the
    first not complete; else the last of them. ``stages`` narrows the search
    to one bracket's (default: every stage). ``now`` must be timezone-aware.
    """
    candidates = config.stages if stages is None else list(stages)
    for stage in candidates:
        if any(r.status == RaceStatus.RUNNING for _, r in resolved.stage_races.get(stage.key, [])):
            return stage.key
    today = now.astimezone(UTC).date()
    todays = [s for s in candidates if today in _stage_days(s, resolved)]

    def started(stage: EventStage) -> bool:
        return any(r.status != RaceStatus.SETUP for _, r in resolved.stage_races.get(stage.key, []))

    for stage in todays:
        if started(stage) and not resolved.results[stage.key].complete:
            return stage.key
    for stage in todays:
        if not resolved.results[stage.key].complete:
            return stage.key
    return todays[-1].key if todays else None


def next_stage_key(
    config: EventConfig,
    resolved: ResolvedStages,
    now: datetime,
    stages: Sequence[EventStage] | None = None,
) -> str | None:
    """The next evening that can honestly be announced, or None.

    The earliest stage ahead of ``now``, not complete, that waits on no stage
    without a date: a final is not "next" while a semi feeding it has none.
    ``stages`` narrows the search to one bracket's (default: every stage).
    """

    def waits_on_undated(stage: EventStage) -> bool:
        for key in stage.source_keys:
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
            for stage in (config.stages if stages is None else stages)
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


# --- playoff cutoff ---------------------------------------------------------


async def update_playoff_cutoff(db: AsyncSession, race: Race, *, only_lower: bool = True) -> bool:
    """Bring a stage or showcase race's ``igt_cutoff_ms`` to its playoff deadline.

    Called on every finish with ``only_lower``: the first one sets the
    deadline (``playoff_deadline_ms``), a later, faster one lowers it, and a
    lower deadline already stored stands, so concurrent finishes settle on the
    lowest. A disqualification or its cancellation changes which runs are
    finished, so it recomputes without ``only_lower``: the deadline can go up,
    or away once no finished run stands. ``race`` must have its participants
    loaded. The write is conditional on the race running, so a race that just
    ended is never broadcast back as running. Returns whether the cutoff moved.
    """
    if not race.is_event_stage or race.event_id is None:
        return False
    event = await db.get(Event, race.event_id)
    try:
        config = EventConfig.model_validate(event.config if event is not None else None)
    except ValidationError:
        # The race keeps running without a cutoff.
        logger.warning("Playoff cutoff skipped for race %s: no valid event config", race.id)
        return False
    deadline = playoff_deadline_ms(race, config)
    moves: ColumnElement[bool]
    if deadline is None:
        if only_lower:
            return False
        moves = Race.igt_cutoff_ms.is_not(None)
    elif only_lower:
        moves = or_(Race.igt_cutoff_ms.is_(None), Race.igt_cutoff_ms > deadline)
    else:
        moves = or_(Race.igt_cutoff_ms.is_(None), Race.igt_cutoff_ms != deadline)
    result = await db.execute(
        update(Race)
        .where(Race.id == race.id, Race.status == RaceStatus.RUNNING, moves)
        .values(igt_cutoff_ms=deadline)
    )
    await db.commit()
    if result.rowcount == 0:  # type: ignore[attr-defined]
        return False
    race.igt_cutoff_ms = deadline
    return True


def is_event_joinable(event: Event, now: datetime) -> bool:
    """Whether runners can still join ``event`` (sign up, enter a qualifier)."""
    starts_at, qualifier_ends_at, ends_at = event_window(event)
    config = EventConfig.model_validate(event.config)
    # Whether the brackets are complete only tells playoffs from finished,
    # neither of which can be joined, so the stage races are not needed here.
    phase = compute_phase(
        now=now,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=first_config_date(config),
        brackets_complete=False,
        override=config.phase_override,
    )
    return phase in JOINABLE_PHASES
