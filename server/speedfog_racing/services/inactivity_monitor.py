"""Background task to auto-abandon inactive or no-show participants."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import contains_eager, selectinload

from speedfog_racing.discord import fire_race_finished_notifications
from speedfog_racing.models import (
    ChatChannel,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    compute_late_join_deadlines,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.services.relay import (
    abandon_team,
    apply_member_out,
    is_active_member,
    leaderboard_entries,
)
from speedfog_racing.websocket.schemas import persist_system_chat

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = timedelta(minutes=30)
POLL_INTERVAL = 60  # seconds

# Public chat line of a runner abandoned for inactivity ({name}: their display name).
INACTIVITY_LINE = "{name} has abandoned the race due to inactivity."

# A relay team still in the race (READY until its first holder's report).
_TEAM_IN_RACE = (ParticipantStatus.READY, ParticipantStatus.PLAYING)


def _utc(moment: datetime | None) -> datetime | None:
    """``moment`` read as UTC (SQLite returns naive datetimes)."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


async def abandon_inactive_participants(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[list[uuid.UUID], set[uuid.UUID]]:
    """Find and abandon inactive participants in running races.

    Daily-seed races are skipped entirely: their async multi-hour window
    makes inactivity-based abandonment misleading.

    Two branches:
    - PLAYING with stale IGT (older than INACTIVITY_TIMEOUT).
    - No-show REGISTERED/READY: gated on race_duration_minutes IS NULL
      (hard-close handles sweeping otherwise). Cutoff is per-participant
      via ``max(Race.started_at, Participant.created_at) < cutoff``,
      expressed as two ANDed conditions, so neither a late-joiner nor an
      early registrant gets abandoned spuriously at race start. When a
      late-join window is configured, the race-start anchor is pushed to
      the window close (``started_at + late_join_window_minutes``): a
      registrant who plans to connect during the window must not be swept
      before it elapses. That offset is applied in Python (below) since
      ``started_at + window`` is dialect-specific in SQL; the SQL
      ``Race.started_at < cutoff`` predicate stays as a coarse pre-filter
      (a necessary condition, the window close is always later).

    A relay race member is judged the same way, ``last_igt_change_at``
    holding there since when their mod is offline (a waiting runner is idle by
    design, so a connected one is never inactive), but goes out through the
    baton's locks (``take_member_out``): a baton they held is freed, the cap
    recomputed, the team put out when nobody is left, and the chat lines
    (theirs, the team's) are posted there.

    Returns (race_ids with abandonments, participant_ids that were just
    abandoned). Caller is responsible for the auto-finish check and
    broadcasts.
    """
    from speedfog_racing.websocket.race.relay import take_member_out

    cutoff = datetime.now(UTC) - INACTIVITY_TIMEOUT
    affected_race_ids: list[uuid.UUID] = []
    abandoned_participant_ids: set[uuid.UUID] = set()
    relay_members: list[tuple[uuid.UUID, uuid.UUID]] = []

    async with session_maker() as db:
        result = await db.execute(
            select(Participant)
            .join(Participant.race)
            .options(contains_eager(Participant.race))
            .where(
                Race.status == RaceStatus.RUNNING,
                Race.daily_date.is_(None),
                or_(
                    # PLAYING with stale IGT
                    (Participant.status == ParticipantStatus.PLAYING)
                    & Participant.last_igt_change_at.isnot(None)
                    & (Participant.last_igt_change_at < cutoff),
                    # Never connected (still REGISTERED/READY after race started).
                    # Skipped when race_duration_minutes is set: hard_close_loop
                    # will move non-terminal participants to ABANDONED at the
                    # deadline via finalize_race.
                    Participant.status.in_([ParticipantStatus.REGISTERED, ParticipantStatus.READY])
                    & Race.race_duration_minutes.is_(None)
                    & Race.started_at.isnot(None)
                    & (Race.started_at < cutoff)
                    & (Participant.created_at < cutoff),
                ),
            )
        )
        stale_participants = result.scalars().unique().all()

        for p in stale_participants:
            # No-show branch only: defer abandonment until the late-join window
            # has closed (start + window). The PLAYING branch is anchored on
            # per-participant IGT activity and needs no window adjustment.
            if p.status != ParticipantStatus.PLAYING:
                registration_closes_at, _ = compute_late_join_deadlines(p.race)
                if registration_closes_at is not None and registration_closes_at >= cutoff:
                    continue

            if p.race.is_relay:
                relay_members.append((p.race_id, p.id))
                continue

            reason = (
                f"last IGT change: {p.last_igt_change_at}"
                if p.status == ParticipantStatus.PLAYING
                else f"no-show after race start (status: {p.status.value})"
            )
            logger.info("Auto-abandoning participant %s (%s)", p.id, reason)
            p.status = ParticipantStatus.ABANDONED
            abandoned_participant_ids.add(p.id)
            if p.race_id not in affected_race_ids:
                affected_race_ids.append(p.race_id)

        if abandoned_participant_ids:
            await db.commit()

    # Once the session above is closed: each runs in a session of its own, and
    # one failing (a deadlock abort) neither stops the others nor loses the
    # abandons committed above.
    for race_id, participant_id in relay_members:
        try:
            out = await take_member_out(
                session_maker,
                race_id,
                participant_id,
                _still_inactive(cutoff),
                member_line=(ChatChannel.PUBLIC, INACTIVITY_LINE),
            )
        except Exception:
            logger.exception("Relay member inactivity failed: %s", participant_id)
            continue
        if out is None:
            continue
        logger.info("Auto-abandoning relay member %s (offline or no-show)", participant_id)
        abandoned_participant_ids.add(participant_id)
        if race_id not in affected_race_ids:
            affected_race_ids.append(race_id)

    return affected_race_ids, abandoned_participant_ids


def _still_inactive(cutoff: datetime) -> Callable[[RelayTeam, Participant], bool]:
    """A relay member found inactive, judged again on their row read under the
    baton's locks (their mod may have come back meanwhile): offline since
    before ``cutoff`` while PLAYING, or still a no-show. Abandons them."""

    def out(team: RelayTeam, member: Participant) -> bool:
        since = _utc(member.last_igt_change_at)
        inactive = team.race.status == RaceStatus.RUNNING and (
            (member.status == ParticipantStatus.PLAYING and since is not None and since < cutoff)
            or member.status in (ParticipantStatus.REGISTERED, ParticipantStatus.READY)
        )
        if inactive:
            member.status = ParticipantStatus.ABANDONED
        return inactive

    return out


async def abandon_stale_relay_teams(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[list[uuid.UUID], set[uuid.UUID]]:
    """Relay teams whose IGT went stale, the relay form of the PLAYING branch.

    A team in the race (PLAYING, or READY with a stamp: its first holder never
    reported, then went out) whose ``last_igt_change_at`` is older than
    ``INACTIVITY_TIMEOUT`` has its holder abandoned (through ``member_out``:
    the baton freed, the cap recomputed, the team out when nobody is left),
    and its stamp restarts, so a free baton gets 30 minutes of its own (as one
    freed by any holder going out). A team without holder (a free baton nobody
    took in that time) is out itself. Waiting runners are idle by design: only
    the team's IGT is watched. The chat lines are posted there. A team whose
    operation fails is logged and skipped: the others still go.

    Returns (race_ids touched, holders just abandoned). Caller is responsible
    for the auto-finish check and broadcasts.
    """
    from speedfog_racing.websocket.race.relay import member_out

    cutoff = datetime.now(UTC) - INACTIVITY_TIMEOUT
    async with session_maker() as db:
        rows = (
            await db.execute(
                select(RelayTeam.race_id, RelayTeam.id)
                .join(Race, Race.id == RelayTeam.race_id)
                .where(
                    Race.status == RaceStatus.RUNNING,
                    RelayTeam.status.in_(_TEAM_IN_RACE),
                    RelayTeam.last_igt_change_at.isnot(None),
                    RelayTeam.last_igt_change_at < cutoff,
                )
            )
        ).all()

    affected_race_ids: list[uuid.UUID] = []
    abandoned_holder_ids: set[uuid.UUID] = set()
    for race_id, team_id in rows:
        try:
            out = await member_out(
                session_maker,
                race_id,
                _stale_team_out(cutoff),
                team_id=team_id,
                member_line=(ChatChannel.PUBLIC, INACTIVITY_LINE),
            )
        except Exception:
            logger.exception("Relay team inactivity failed: %s", team_id)
            continue
        if out is None:
            continue
        logger.info("Relay team %s inactive: holder %s out", team_id, out.member_id)
        if out.member_id is not None:
            abandoned_holder_ids.add(out.member_id)
        if race_id not in affected_race_ids:
            affected_race_ids.append(race_id)
    return affected_race_ids, abandoned_holder_ids


def _stale_team_out(
    cutoff: datetime,
) -> Callable[[RelayTeam], tuple[Participant | None, bool] | None]:
    """The stale-team rule on the team read under the baton's locks (it may
    have moved meanwhile). Freeing the holder's baton restarts the team's
    stamp (``apply_member_out``)."""

    def change(team: RelayTeam) -> tuple[Participant | None, bool] | None:
        since = _utc(team.last_igt_change_at)
        if (
            team.race.status != RaceStatus.RUNNING
            or team.status not in _TEAM_IN_RACE
            or since is None
            or since >= cutoff
        ):
            return None
        holder = next(
            (m for m in team.members if m.id == team.holder_id and is_active_member(m)), None
        )
        if holder is None:
            abandon_team(team, team.members)
            return None, True
        holder.status = ParticipantStatus.ABANDONED
        return holder, apply_member_out(team, team.members, holder)

    return change


async def _expire_speedrun_sessions(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Abandon expired Speedrun solo sessions and tell their connections."""
    from speedfog_racing.services.training_service import expire_speedrun_sessions
    from speedfog_racing.websocket.training.mod import _broadcast_status_change

    async with session_maker() as db:
        expired = await expire_speedrun_sessions(db, now=datetime.now(UTC))
    for session_id in expired:
        await _broadcast_status_change(session_id, "abandoned")


async def inactivity_monitor_loop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodic loop that checks for inactive participants."""
    logger.info(
        "Inactivity monitor started (timeout=%s, poll=%ds)",
        INACTIVITY_TIMEOUT,
        POLL_INTERVAL,
    )
    while True:
        try:
            await _expire_speedrun_sessions(session_maker)
        except Exception:
            logger.exception("Speedrun session expiry error")
        try:
            affected, abandoned_ids = await abandon_inactive_participants(session_maker)
            try:
                stale_races, stale_holders = await abandon_stale_relay_teams(session_maker)
            except Exception:
                # The abandons above are committed: their follow-up still runs.
                logger.exception("Relay stale-team check failed")
                stale_races, stale_holders = [], set()
            affected += [race_id for race_id in stale_races if race_id not in affected]
            abandoned_ids |= stale_holders
            if affected:
                from speedfog_racing.websocket.race.manager import manager
                from speedfog_racing.websocket.race.spectator import broadcast_race_state_update

                for race_id in affected:
                    # One session per affected race: load Race with the full
                    # option chain (participants+users, casters, seed), run
                    # the auto-finish check, then broadcast.
                    async with session_maker() as db:
                        result = await db.execute(
                            select(Race)
                            .where(Race.id == race_id)
                            .options(
                                selectinload(Race.participants).selectinload(Participant.user),
                                selectinload(Race.casters),
                                selectinload(Race.seed),
                            )
                        )
                        race = result.scalar_one_or_none()
                        if race is None:
                            continue

                        if race.status == RaceStatus.RUNNING:
                            await check_race_auto_finish(db, race)

                        room = manager.get_room(race_id)
                        if room:
                            for p in race.participants:
                                if p.status == ParticipantStatus.ABANDONED:
                                    room.set_participant_status(
                                        p.user_id, ParticipantStatus.ABANDONED
                                    )

                        # Persist "abandoned due to inactivity" messages for
                        # newly abandoned participants (persist unconditionally
                        # so history replays on reconnect; broadcast only if a
                        # room exists). A relay race's were posted where its
                        # members went out, with their team's.
                        abandon_messages: list[str] = []
                        for p in race.participants:
                            if p.id in abandoned_ids and not race.is_relay:
                                display = p.user.twitch_display_name or p.user.twitch_username
                                abandon_msg = INACTIVITY_LINE.format(name=display)
                                sys_json = await persist_system_chat(
                                    db,
                                    race_id,
                                    ChatChannel.PUBLIC,
                                    abandon_msg,
                                )
                                abandon_messages.append(sys_json)

                        finish_public_json: str | None = None
                        if race.status == RaceStatus.FINISHED:
                            finish_public_json = await persist_system_chat(
                                db, race_id, ChatChannel.PUBLIC, "The race has finished."
                            )
                        await db.commit()

                        if room:
                            for sys_json in abandon_messages:
                                await room.broadcast_chat_public(sys_json, race)

                        graph_json = race.seed.graph_json if race.seed else None
                        await manager.broadcast_leaderboard(
                            race_id,
                            leaderboard_entries(race, graph_json),
                            graph_json=graph_json,
                            project_ghosts=race.projects_ghosts,
                        )
                        await broadcast_race_state_update(race_id, race)
                        if race.status == RaceStatus.FINISHED:
                            await manager.broadcast_race_status(race_id, "finished")
                            if room and finish_public_json is not None:
                                await room.broadcast_chat_public(finish_public_json, race)
                            fire_race_finished_notifications(race)
        except Exception:
            logger.exception("Inactivity monitor error")

        await asyncio.sleep(POLL_INTERVAL)
