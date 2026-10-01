"""Public tournament event endpoint: one request feeds the event page."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.api.helpers import race_response
from speedfog_racing.auth import get_current_user, get_current_user_optional, require_not_banned
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Event,
    EventSignup,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    compute_late_join_deadlines,
)
from speedfog_racing.schemas import (
    EventConfig,
    EventDetailResponse,
    EventFieldSlotResponse,
    EventLadderEntryResponse,
    EventLadderResponse,
    EventLiveRaceResponse,
    EventMyResultResponse,
    EventNextStageResponse,
    EventQualifiedGroupResponse,
    EventQualifiedResponse,
    EventQualifiedSlotResponse,
    EventQualifierRaceResponse,
    EventShowcase,
    EventStage,
    EventStageEntryResponse,
    EventStageRaceResponse,
    EventStageResponse,
    EventSummaryResponse,
    EventTimelineStopResponse,
    EventWeaponResponse,
    UserResponse,
)
from speedfog_racing.services.event_service import (
    JOINABLE_PHASES,
    MAX_PLAYER_PREVIEWS,
    MIN_UPCOMING_PLAYERS,
    Slot,
    StageResult,
    announce_date,
    build_timeline,
    compute_ladder,
    compute_qualified,
    count_finished_before,
    current_stage_key,
    event_window,
    fed_field,
    is_event_joinable,
    load_event,
    load_featured_events,
    newcomer_flags,
    next_stage_key,
    resolve_stages,
    resolve_withdrawn,
    score_race,
    showcase_field,
    signature_weapon,
    slot_label,
)

router = APIRouter()

# Registered or ready: the viewer joined the seed but has not run it yet.
_JOINED = {ParticipantStatus.REGISTERED, ParticipantStatus.READY}


def _my_result(race: Race, user: User | None) -> EventMyResultResponse | None:
    if user is None:
        return None
    mine: Participant | None = next((p for p in race.participants if p.user_id == user.id), None)
    if mine is None:
        return EventMyResultResponse(status="not_played")
    if mine.status in _JOINED:
        return EventMyResultResponse(status="joined")
    if mine.status == ParticipantStatus.PLAYING:
        return EventMyResultResponse(status="playing")
    finished = mine.status == ParticipantStatus.FINISHED
    # Same field as the ladder, so the seed card and the ladder show the same points.
    score = score_race(race, settled_only=True).get(user.id)
    if score is None:
        return EventMyResultResponse(status="done", finished=finished, igt_ms=mine.igt_ms)
    return EventMyResultResponse(
        status="done",
        finished=finished,
        rank=score.rank,
        igt_ms=score.igt_ms,
        points=score.points,
        provisional=score.provisional,
    )


@router.get("", response_model=list[EventSummaryResponse])
async def list_events(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[EventSummaryResponse]:
    """The events on the bill: what the home page band and the navbar show.

    A finished season (kept for its champion) yields the head of the list to
    one still to come, so a season announced right after the last final is
    what the band shows; otherwise the earliest season leads.
    """
    now = datetime.now(UTC)
    summaries: list[EventSummaryResponse] = []
    for event in await load_featured_events(db, now):
        starts_at, qualifier_ends_at, ends_at = event_window(event)
        config = EventConfig.model_validate(event.config)

        resolved = resolve_stages(event, config, now)
        stage_races, results, phase = resolved.stage_races, resolved.results, resolved.phase
        final = config.final_stage()

        # The Open Graph card's count and order: everyone who joined an event
        # race (a showcase's hand-picked runners aside), plus the signups while
        # the event can still be joined, the ladder's best first and the
        # runners it could not rank after them; nothing while an upcoming event
        # has too few of them to advertise.
        showcase_ids = resolved.showcase_race_ids
        users: dict[UUID, User] = {
            p.user_id: p.user
            for race in event.races
            if race.id not in showcase_ids
            for p in race.participants
        }
        signed_up: list[UUID] = []
        if phase in JOINABLE_PHASES:
            signed_up = [s.user_id for s in event.signups]
            users.update({s.user_id: s.user for s in event.signups})
        mode_keys = config.mode_keys()
        ladder = compute_ladder(mode_keys, resolved.qualifier, signed_up=signed_up)
        ranked_ids = {entry.user_id for entry in ladder}
        ordered = [users[entry.user_id] for entry in ladder if entry.user_id in users]
        ordered += sorted(
            (user for user_id, user in users.items() if user_id not in ranked_ids),
            key=lambda u: u.twitch_username,
        )
        players = len(users)
        previews = ordered[:MAX_PLAYER_PREVIEWS]
        if phase == "upcoming" and players < MIN_UPCOMING_PLAYERS:
            players, previews = 0, []

        live = None
        running = next(
            (
                (stage, slot, r)
                for stage in config.stages
                for slot, r in stage_races[stage.key]
                if r.status == RaceStatus.RUNNING
            ),
            None,
        )
        if running is not None:
            stage, slot, race = running
            live = EventLiveRaceResponse(
                race=race_response(race, user),
                stage_label=stage.label,
                index=slot.index,
                races_expected=stage.races,
            )
        upcoming_key = next_stage_key(config, resolved, now)
        upcoming = config.stage(upcoming_key) if upcoming_key else None
        next_stage = None
        if upcoming is not None:
            upcoming_date = resolved.dates[upcoming.key]
            assert upcoming_date is not None, "next_stage_key only returns dated stages"
            next_stage = EventNextStageResponse(
                key=upcoming.key, label=upcoming.label, date=upcoming_date
            )
        champion = None
        if phase == "finished" and final is not None and results[final.key].complete:
            leader = next(iter(results[final.key].entries), None)
            if leader is not None and leader.user_id in users:
                champion = UserResponse.model_validate(users[leader.user_id])

        summaries.append(
            EventSummaryResponse(
                slug=event.slug,
                name=event.name,
                partner_name=event.partner_name,
                partner_logo_url=event.partner_logo_url,
                starts_at=starts_at,
                qualifier_ends_at=qualifier_ends_at,
                ends_at=ends_at,
                phase=phase,
                my_signup=user is not None and any(s.user_id == user.id for s in event.signups),
                players=players,
                player_previews=[UserResponse.model_validate(u) for u in previews],
                next_stage=next_stage,
                live=live,
                champion=champion,
            )
        )
    summaries.sort(key=lambda s: (s.phase == "finished", s.starts_at))
    return summaries


@router.get("/{slug}", response_model=EventDetailResponse)
async def get_event(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> EventDetailResponse:
    event = await load_event(db, slug)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    starts_at, qualifier_ends_at, ends_at = event_window(event)
    config = EventConfig.model_validate(event.config)
    now = datetime.now(UTC)

    resolved = resolve_stages(event, config, now)
    attached, qualifier = resolved.attached, resolved.qualifier
    stage_races, results, phase = resolved.stage_races, resolved.results, resolved.phase
    mode_keys = config.mode_keys()

    users: dict[UUID, User] = {p.user_id: p.user for race in event.races for p in race.participants}
    users.update({s.user_id: s.user for s in event.signups})
    histories: dict[UUID, list[list[dict[str, Any]]]] = {}
    showcase_ids = resolved.showcase_race_ids
    for _, race in attached:
        if race.id in showcase_ids:
            continue
        for p in race.participants:
            histories.setdefault(p.user_id, []).append(p.zone_history or [])
    weapons: dict[UUID, EventWeaponResponse | None] = {}

    def weapon_of(user_id: UUID) -> EventWeaponResponse | None:
        if user_id not in weapons:
            found = signature_weapon(histories.get(user_id, []))
            weapons[user_id] = EventWeaponResponse(id=found[0], name=found[1]) if found else None
        return weapons[user_id]

    labels = {s.key: s.label for s in config.stages}

    # Before the opening the seed slots render as placeholders: the attached
    # races stay out of the response, so their ids cannot lead anyone to a
    # pack released early for the organizer to check the seed.
    shown_qualifier = qualifier if phase != "upcoming" else []

    signed_up = [s.user_id for s in event.signups] if phase in JOINABLE_PHASES else []
    ladder = compute_ladder(mode_keys, qualifier, signed_up=signed_up)
    finished_before = await count_finished_before(db, set(users), announce_date(event, config))
    newcomers = newcomer_flags(finished_before, event.newcomer_threshold, users.keys())
    ladder_final = bool(qualifier) and all(r.status == RaceStatus.FINISHED for _, r in qualifier)
    started = {
        key
        for key, races in stage_races.items()
        if any(r.status != RaceStatus.SETUP for _, r in races)
    }
    qualified = compute_qualified(
        ladder, config, newcomers, resolve_withdrawn(config.withdrawn, users), ladder_final, started
    )
    # Config stage order, then by index within a stage: a race attached under a
    # slot key no longer in the config never becomes the live race, and ties
    # between two RUNNING stage races resolve deterministically.
    live = next(
        (
            r
            for stage in config.stages
            for _, r in stage_races[stage.key]
            if r.status == RaceStatus.RUNNING
        ),
        None,
    )
    upcoming_key = next_stage_key(config, resolved, now)
    upcoming = config.stage(upcoming_key) if upcoming_key else None
    next_stage = None
    if upcoming is not None:
        upcoming_date = resolved.dates[upcoming.key]
        assert upcoming_date is not None, "next_stage_key only returns dated stages"
        next_stage = EventNextStageResponse(
            key=upcoming.key, label=upcoming.label, date=upcoming_date
        )

    def user_of(user_id: UUID | None) -> UserResponse | None:
        return UserResponse.model_validate(users[user_id]) if user_id in users else None

    def stage_response(
        stage: EventStage | EventShowcase,
        *,
        kind: str,
        sources: list[str],
        date: datetime | None,
        races: list[tuple[Slot, Race]],
        result: StageResult,
        field: list[EventFieldSlotResponse],
    ) -> EventStageResponse:
        return EventStageResponse(
            key=stage.key,
            label=stage.label,
            kind=kind,
            date=date,
            date_fixed=stage.date is not None,
            from_=sources,  # type: ignore[call-arg]  # mypy ignores populate_by_name
            races_expected=stage.races,
            complete=result.complete,
            modes=stage.modes,
            races=[
                EventStageRaceResponse(slot=str(s), index=s.index, race=race_response(r, user))
                for s, r in races
            ],
            results=[
                EventStageEntryResponse(
                    user=UserResponse.model_validate(users[e.user_id]),
                    newcomer=newcomers.get(e.user_id, False),
                    points=e.points,
                    igt_total=e.igt_total,
                    advances=e.advances,
                    signature_weapon=weapon_of(e.user_id),
                )
                for e in result.entries
            ],
            field=field,
        )

    def field_of(stage_key: str) -> list[EventFieldSlotResponse]:
        stage = config.stage(stage_key)
        if stage is None:
            return []
        if stage.from_:
            return [
                EventFieldSlotResponse(user=user_of(slot.user_id), label=slot.label)
                for slot in fed_field(stage, config, results)
            ]
        return [
            EventFieldSlotResponse(user=user_of(slot.user_id), label=slot_label(slot))
            for slot in qualified.get(stage_key, [])
        ]

    return EventDetailResponse(
        slug=event.slug,
        name=event.name,
        partner_name=event.partner_name,
        partner_url=event.partner_url,
        partner_logo_url=event.partner_logo_url,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        newcomer_threshold=event.newcomer_threshold,
        phase=phase,
        ladder_final=ladder_final,
        my_signup=user is not None and any(s.user_id == user.id for s in event.signups),
        modes=config.modes,
        seeds_per_mode=config.seeds_per_mode,
        rules=config.rules,
        playoff_rules=config.playoff_rules,
        facts=config.facts,
        timeline=[
            EventTimelineStopResponse(key=s.key, label=s.label, date=s.date, kind=s.kind)
            for s in build_timeline(event, config, resolved.dates)
        ],
        qualifier_races=[
            EventQualifierRaceResponse(
                slot=str(slot),
                mode=slot.key,
                index=slot.index,
                race=race_response(race, user),
                closes_at=compute_late_join_deadlines(race)[1],
                my_result=_my_result(race, user),
            )
            for slot, race in shown_qualifier
        ],
        ladder=EventLadderResponse(
            provisional=not ladder_final,
            # A run-derived entry always has a counted mode, so modes_scored
            # splits runs from signups.
            entered=sum(1 for e in ladder if e.modes_scored > 0),
            ranked_count=sum(1 for e in ladder if e.rank is not None),
            signed_up=sum(1 for e in ladder if e.modes_scored == 0),
            entries=[
                EventLadderEntryResponse(
                    rank=e.rank,
                    user=UserResponse.model_validate(users[e.user_id]),
                    newcomer=newcomers.get(e.user_id, False),
                    mode_points=e.mode_points,
                    total=e.total,
                    modes_scored=e.modes_scored,
                    igt_total=e.igt_total,
                    provisional=e.provisional,
                )
                for e in ladder
            ],
        ),
        qualified=EventQualifiedResponse(
            provisional=not ladder_final,
            groups=[
                EventQualifiedGroupResponse(
                    stage_key=key,
                    label=labels[key],
                    entries=[
                        EventQualifiedSlotResponse(
                            seed=slot.seed,
                            user=user_of(slot.user_id),
                            newcomer=newcomers.get(slot.user_id, False) if slot.user_id else False,
                            note=slot.note,
                        )
                        for slot in slots
                    ],
                )
                for key, slots in qualified.items()
            ],
        ),
        stages=[
            stage_response(
                stage,
                kind=stage.kind,
                sources=stage.from_ or [],
                date=resolved.dates[stage.key],
                races=stage_races[stage.key],
                result=results[stage.key],
                field=field_of(stage.key),
            )
            for stage in config.stages
        ],
        showcases=[
            stage_response(
                showcase,
                kind="showcase",
                sources=[],
                date=resolved.showcase_dates[showcase.key],
                races=resolved.showcase_races[showcase.key],
                result=resolved.showcase_results[showcase.key],
                field=[
                    EventFieldSlotResponse(user=user_of(slot.user_id), label=slot.label)
                    for slot in showcase_field(
                        showcase, [r for _, r in resolved.showcase_races[showcase.key]]
                    )
                ],
            )
            for showcase in config.showcases
        ],
        current_stage_key=(
            current_stage_key(config, resolved, now) if phase == "playoffs" else None
        ),
        live_race=race_response(live, user) if live is not None else None,
        next_stage=next_stage,
    )


async def _joinable_event(db: AsyncSession, slug: str) -> Event:
    """The event behind ``slug``, or 404; 400 once it can no longer be joined."""
    event = (await db.execute(select(Event).where(Event.slug == slug))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if not is_event_joinable(event, datetime.now(UTC)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The event can no longer be joined",
        )
    return event


@router.post("/{slug}/signup", status_code=status.HTTP_204_NO_CONTENT)
async def sign_up(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> None:
    """Say you are in: the ladder lists you before you run. Idempotent."""
    event = await _joinable_event(db, slug)
    db.add(EventSignup(event_id=event.id, user_id=user.id))
    try:
        await db.commit()
    except IntegrityError:
        # Already in, including two clicks racing each other.
        await db.rollback()


@router.delete("/{slug}/signup", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Take your word back. A runner who scored stays on the ladder through their runs."""
    event = await _joinable_event(db, slug)
    await db.execute(
        delete(EventSignup).where(EventSignup.event_id == event.id, EventSignup.user_id == user.id)
    )
    await db.commit()
