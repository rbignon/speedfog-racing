"""Relay race teams: the routes that edit them, and the placement every registration goes through.

Nobody is registered on a relay race without a team: ``join_race``, ``accept_invite``,
``add_participant`` and the team routes all call ``place_in_team``, and every removal
calls ``vacate_team``.
"""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.api import races as races_api
from speedfog_racing.auth import get_current_user, require_not_banned
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    ChatChannel,
    Participant,
    Race,
    RaceStatus,
    RelayTeam,
    User,
    UserRole,
)
from speedfog_racing.schemas import (
    CreateRelayTeamRequest,
    MoveToRelayTeamRequest,
    RaceDetailResponse,
    RelayTeamChoice,
    UpdateRelayTeamRequest,
)
from speedfog_racing.services.calendar_sync import add_calendar_participant
from speedfog_racing.services.relay import default_team_name
from speedfog_racing.websocket import broadcast_race_state_update
from speedfog_racing.websocket.race.manager import manager
from speedfog_racing.websocket.schemas import persist_system_chat

logger = logging.getLogger(__name__)

router = APIRouter()


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


async def _member_count(db: AsyncSession, team_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Participant).where(Participant.relay_team_id == team_id)
    )
    return int(result.scalar_one())


async def _team_in_race(db: AsyncSession, race: Race, team_id: UUID) -> RelayTeam:
    """The race's team, or 404 (a team of another race is not found either)."""
    team = await db.get(RelayTeam, team_id)
    if team is None or team.race_id != race.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def _new_team(
    db: AsyncSession, race: Race, *, name: str | None, placeholder: bool
) -> RelayTeam:
    """An empty team after the race's others, in the next color of the palette."""
    rows = await db.execute(
        select(RelayTeam.name, RelayTeam.color_index).where(RelayTeam.race_id == race.id)
    )
    existing = rows.all()
    team = RelayTeam(
        race_id=race.id,
        name=name or default_team_name({n for n, _ in existing}),
        color_index=max((c for _, c in existing), default=-1) + 1,
        placeholder=placeholder,
    )
    db.add(team)
    await db.flush()
    return team


async def vacate_team(db: AsyncSession, race: Race, participant: Participant) -> None:
    """Take ``participant`` out of its team, before it moves or its row is deleted.

    Clears ``first_runner_id`` when it was them (null means the first member
    registered), and deletes the team when it empties, unless the organizer made
    it (a placeholder stays until he deletes it).
    """
    team_id = participant.relay_team_id
    if team_id is None:
        return
    participant.relay_team_id = None
    team = await db.get(RelayTeam, team_id)
    if team is None:
        return
    if team.first_runner_id == participant.id:
        team.first_runner_id = None
    await db.flush()
    if not team.placeholder and await _member_count(db, team_id) == 0:
        await db.delete(team)
        await db.flush()


async def place_in_team(
    db: AsyncSession,
    race: Race,
    participant: Participant,
    choice: RelayTeamChoice,
    *,
    by_organizer: bool,
) -> RelayTeam | None:
    """Put ``participant`` into the team ``choice`` names, or into a new one.

    Moves them when they are already in a team (the team they leave is vacated).
    Returns None on a race that is not a relay race, where a choice is refused
    and nothing else happens. ``by_organizer`` lets the organizer create a team
    for a runner when runners may not.
    """
    if not race.is_relay:
        if choice.relay_team_id is not None or choice.create_team:
            raise _bad_request("Not a relay race")
        return None
    if choice.create_team == (choice.relay_team_id is not None):
        raise _bad_request("Pick a team to join a relay race")
    team: RelayTeam | None = None
    if choice.create_team:
        if not by_organizer and not race.relay_runners_create_teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Runners cannot create teams on this race",
            )
    else:
        assert choice.relay_team_id is not None
        team = await _team_in_race(db, race, choice.relay_team_id)
        if participant.relay_team_id == team.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already in that team")
        assert race.relay_team_size is not None
        if await _member_count(db, team.id) >= race.relay_team_size:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team is full")
    await db.flush()  # the participant needs its id
    await vacate_team(db, race, participant)
    if team is None:
        team = await _new_team(db, race, name=None, placeholder=False)
        team.first_runner_id = participant.id
    participant.relay_team_id = team.id
    participant.color_index = team.color_index
    await db.flush()
    return team


def _is_organizer(race: Race, user: User) -> bool:
    return race.organizer_id == user.id or user.role == UserRole.ADMIN


async def _load_relay_race(db: AsyncSession, race_id: UUID) -> Race:
    """The race with its participants, which must be a relay race in SETUP."""
    race = await races_api._get_race_or_404(db, race_id, load_participants=True)
    if not race.is_relay:
        raise _bad_request("Not a relay race")
    if race.status != RaceStatus.SETUP:
        raise _bad_request("Teams can only be changed in SETUP status")
    return race


async def _finish(db: AsyncSession, race: Race, user: User) -> RaceDetailResponse:
    """Commit, reload the race, tell the room and answer with the race."""
    await db.commit()
    db.expire(race, ["relay_teams", "participants"])
    race = await races_api._get_race_or_404(
        db, race.id, load_participants=True, load_casters=True, load_invites=True
    )
    graph_json = race.seed.graph_json if race.seed else None
    await manager.broadcast_leaderboard(
        race.id, race.participants, graph_json=graph_json, project_ghosts=race.projects_ghosts
    )
    await broadcast_race_state_update(race.id, race)
    return races_api._race_detail_response(race, user)


async def _register_self(db: AsyncSession, race: Race, user: User) -> Participant:
    """Register ``user`` on the race as ``join_race`` does (checks, row, chat line).

    The caller places the row in a team before committing.
    """
    await races_api.check_self_registration(db, race, user)
    participant = Participant(race_id=race.id, user_id=user.id, color_index=0)
    db.add(participant)
    display = user.twitch_display_name or user.twitch_username
    await persist_system_chat(
        db, race.id, ChatChannel.PARTICIPANTS, f"{display} has joined the race"
    )
    return participant


async def _own_participant(db: AsyncSession, race: Race, user: User) -> Participant | None:
    result = await db.execute(
        select(Participant).where(Participant.race_id == race.id, Participant.user_id == user.id)
    )
    return result.scalar_one_or_none()


def _mirror_join(race: Race, user: User) -> None:
    if race.is_public and race.scheduled_at:
        task = asyncio.create_task(add_calendar_participant(race.id, user.twitch_username))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


@router.post("/{race_id}/relay-teams", response_model=RaceDetailResponse)
async def create_relay_team(
    race_id: UUID,
    request: CreateRelayTeamRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> RaceDetailResponse:
    """The organizer adds an empty placeholder team; a runner creates a team they join."""
    race = await _load_relay_race(db, race_id)
    if _is_organizer(race, user):
        await _new_team(db, race, name=request.name, placeholder=True)
        return await _finish(db, race, user)
    if not race.relay_runners_create_teams:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Runners cannot create teams on this race",
        )
    participant = await _own_participant(db, race, user)
    joined = participant is None
    if participant is None:
        participant = await _register_self(db, race, user)
    await place_in_team(
        db, race, participant, RelayTeamChoice(create_team=True), by_organizer=False
    )
    if request.name:
        team = await db.get(RelayTeam, participant.relay_team_id)
        assert team is not None
        team.name = request.name
    detail = await _finish(db, race, user)
    if joined:
        _mirror_join(race, user)
    return detail


@router.patch("/{race_id}/relay-teams/{team_id}", response_model=RaceDetailResponse)
async def update_relay_team(
    race_id: UUID,
    team_id: UUID,
    request: UpdateRelayTeamRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Rename a team or choose its first runner: its members and the organizer."""
    race = await _load_relay_race(db, race_id)
    team = await _team_in_race(db, race, team_id)
    if not _is_organizer(race, user):
        own = await _own_participant(db, race, user)
        if own is None or own.relay_team_id != team.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a member of the team or the organizer can edit it",
            )
    if request.first_runner_id is not None:
        chosen = next((p for p in race.participants if p.id == request.first_runner_id), None)
        if chosen is None or chosen.relay_team_id != team.id:
            raise _bad_request("The first runner must be a member of the team")
        team.first_runner_id = chosen.id
    if request.name is not None:
        team.name = request.name
    return await _finish(db, race, user)


@router.delete("/{race_id}/relay-teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relay_team(
    race_id: UUID,
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """The organizer deletes an empty team."""
    race = await _load_relay_race(db, race_id)
    races_api._require_organizer(race, user)
    team = await _team_in_race(db, race, team_id)
    if await _member_count(db, team.id) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team has members")
    await db.delete(team)
    await _finish(db, race, user)


@router.post("/{race_id}/relay-teams/{team_id}/join", response_model=RaceDetailResponse)
async def join_relay_team(
    race_id: UUID,
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> RaceDetailResponse:
    """Join the race into this team, or move there from another team."""
    race = await _load_relay_race(db, race_id)
    participant = await _own_participant(db, race, user)
    joined = participant is None
    if participant is None:
        participant = await _register_self(db, race, user)
    await place_in_team(
        db, race, participant, RelayTeamChoice(relay_team_id=team_id), by_organizer=False
    )
    detail = await _finish(db, race, user)
    if joined:
        _mirror_join(race, user)
    return detail


@router.post(
    "/{race_id}/participants/{participant_id}/relay-team", response_model=RaceDetailResponse
)
async def move_participant_to_relay_team(
    race_id: UUID,
    participant_id: UUID,
    request: MoveToRelayTeamRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """The organizer moves a runner to another team."""
    race = await _load_relay_race(db, race_id)
    races_api._require_organizer(race, user)
    participant = next((p for p in race.participants if p.id == participant_id), None)
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    await place_in_team(
        db, race, participant, RelayTeamChoice(relay_team_id=request.team_id), by_organizer=True
    )
    return await _finish(db, race, user)
