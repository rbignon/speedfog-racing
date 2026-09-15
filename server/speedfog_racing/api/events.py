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
from speedfog_racing.auth import get_current_user, get_current_user_optional
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
    EventMyResultResponse,
    EventNextStageResponse,
    EventQualifiedGroupResponse,
    EventQualifiedResponse,
    EventQualifiedSlotResponse,
    EventQualifierRaceResponse,
    EventStageEntryResponse,
    EventStageRaceResponse,
    EventStageResponse,
    EventTimelineStopResponse,
    EventWeaponResponse,
    UserResponse,
)
from speedfog_racing.services.event_service import (
    JOINABLE_PHASES,
    UNDECIDED,
    Slot,
    build_timeline,
    compute_ladder,
    compute_phase,
    compute_qualified,
    compute_stage_results,
    count_finished_before,
    current_stage_key,
    event_window,
    final_field,
    load_event,
    newcomer_flags,
    parse_slot,
    score_race,
    signature_weapon,
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
    score = score_race(race).get(user.id)
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

    users: dict[UUID, User] = {p.user_id: p.user for race in event.races for p in race.participants}
    users.update({s.user_id: s.user for s in event.signups})
    histories: dict[UUID, list[list[dict[str, Any]]]] = {}
    for _, race in attached:
        for p in race.participants:
            histories.setdefault(p.user_id, []).append(p.zone_history or [])
    weapons: dict[UUID, EventWeaponResponse | None] = {}

    def weapon_of(user_id: UUID) -> EventWeaponResponse | None:
        if user_id not in weapons:
            found = signature_weapon(histories.get(user_id, []))
            weapons[user_id] = EventWeaponResponse(id=found[0], name=found[1]) if found else None
        return weapons[user_id]

    final = config.final_stage()
    advance = (final.advance or 0) if final is not None else 0
    results = {
        stage.key: compute_stage_results(
            stage,
            [r for _, r in stage_races[stage.key]],
            advance if stage.kind == "semi" else 0,
        )
        for stage in config.stages
    }
    labels = {s.key: s.label for s in config.stages}
    last = config.stages[-1] if config.stages else None
    phase = compute_phase(
        now=now,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=config.stages[0].date if config.stages else None,
        last_stage_complete=results[last.key].complete if last is not None else False,
        override=config.phase_override,
    )

    signed_up = [s.user_id for s in event.signups] if phase in JOINABLE_PHASES else []
    ladder = compute_ladder(mode_keys, qualifier, signed_up=signed_up)
    finished_before = await count_finished_before(db, set(users), starts_at)
    newcomers = newcomer_flags(finished_before, event.newcomer_threshold, users.keys())
    qualified = compute_qualified(ladder, config, newcomers)
    ladder_final = bool(qualifier) and all(r.status == RaceStatus.FINISHED for _, r in qualifier)
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
    upcoming = next((s for s in config.stages if s.date > now), None)

    def user_of(user_id: UUID | None) -> UserResponse | None:
        return UserResponse.model_validate(users[user_id]) if user_id in users else None

    def field_of(stage_key: str) -> list[EventFieldSlotResponse]:
        stage = config.stage(stage_key)
        if stage is None:
            return []
        if stage.kind == "final":
            return [
                EventFieldSlotResponse(user=user_of(slot.user_id), label=slot.label)
                for slot in final_field(stage, results, labels)
            ]
        return [
            EventFieldSlotResponse(
                user=user_of(slot.user_id),
                label=f"Seed {slot.seed}" if slot.seed is not None else UNDECIDED,
            )
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
            for s in build_timeline(event, config)
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
            for slot, race in qualifier
        ],
        ladder=EventLadderResponse(
            provisional=not ladder_final,
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
            EventStageResponse(
                key=stage.key,
                label=stage.label,
                kind=stage.kind,
                date=stage.date,
                races_expected=stage.races,
                complete=results[stage.key].complete,
                modes=stage.modes,
                races=[
                    EventStageRaceResponse(slot=str(s), index=s.index, race=race_response(r, user))
                    for s, r in stage_races[stage.key]
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
                    for e in results[stage.key].entries
                ],
                field=field_of(stage.key),
            )
            for stage in config.stages
        ],
        current_stage_key=current_stage_key(config, now) if phase == "playoffs" else None,
        live_race=race_response(live, user) if live is not None else None,
        next_stage=(
            EventNextStageResponse(key=upcoming.key, label=upcoming.label, date=upcoming.date)
            if upcoming is not None
            else None
        ),
    )


async def _joinable_event(db: AsyncSession, slug: str) -> Event:
    """The event behind ``slug``, or 404; 400 once it can no longer be joined."""
    event = (await db.execute(select(Event).where(Event.slug == slug))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    starts_at, qualifier_ends_at, ends_at = event_window(event)
    config = EventConfig.model_validate(event.config)
    # Whether the last stage is complete only tells playoffs from finished,
    # neither of which can be joined, so the stage races are not loaded here.
    phase = compute_phase(
        now=datetime.now(UTC),
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=config.stages[0].date if config.stages else None,
        last_stage_complete=False,
        override=config.phase_override,
    )
    if phase not in JOINABLE_PHASES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The event can no longer be joined",
        )
    return event


@router.post("/{slug}/signup", status_code=status.HTTP_204_NO_CONTENT)
async def sign_up(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
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
