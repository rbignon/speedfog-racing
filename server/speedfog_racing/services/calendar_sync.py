"""Cross-provider calendar sync (Discord scheduled events + events.malenia.win).

Owns the create/update/delete lifecycle for calendar events across both
providers so the API routes stay provider-agnostic. This module is the only
place that writes ``Race.discord_event_id`` / ``Race.malenia_event_id`` (the
start and delete race routes still read them, to drive Discord status and
teardown).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.database import async_session_maker
from speedfog_racing.discord import (
    create_scheduled_event,
    delete_scheduled_event,
    update_scheduled_event,
)
from speedfog_racing.malenia import (
    add_event_participant,
    create_calendar_event,
    delete_calendar_event,
    remove_event_participant_by_login,
    update_calendar_event,
)
from speedfog_racing.models import Participant, Race

# Seed.pool is lazy="joined", so loading the seed brings the pool along.
_LOAD_OPTS = (
    selectinload(Race.seed),
    selectinload(Race.organizer),
    selectinload(Race.participants).selectinload(Participant.user),
)


def _qualifies(race: Race) -> bool:
    return bool(race.is_public and race.scheduled_at)


async def _create_on_providers(session: AsyncSession, race: Race) -> None:
    """Create the event on both providers, persist ids, and seed malenia participants."""
    assert race.scheduled_at is not None  # guaranteed by _qualifies
    mode_display = format_pool_display_name(race.seed.pool if race.seed else None)
    participant_logins = [p.user.twitch_username for p in race.participants]
    discord_id = await create_scheduled_event(
        race_name=race.name, race_id=str(race.id), scheduled_at=race.scheduled_at
    )
    malenia_id = await create_calendar_event(
        race_name=race.name,
        race_id=str(race.id),
        organizer_login=race.organizer.twitch_username,
        scheduled_at=race.scheduled_at,
        mode_display=mode_display,
        custom_rules=race.custom_rules,
    )
    if discord_id:
        race.discord_event_id = discord_id
    if malenia_id:
        race.malenia_event_id = malenia_id
    if discord_id or malenia_id:
        await session.commit()
    if malenia_id:
        for login in participant_logins:
            await add_event_participant(malenia_id, login)


async def create_calendar_events(race_id: UUID) -> None:
    """Create the calendar event on both providers for a newly created race."""
    async with async_session_maker() as session:
        race = (
            await session.execute(select(Race).where(Race.id == race_id).options(*_LOAD_OPTS))
        ).scalar_one_or_none()
        if race is None or not _qualifies(race):
            return
        await _create_on_providers(session, race)


async def update_calendar_events(
    race_id: UUID,
    *,
    scheduled_changed: bool,
    metadata_changed: bool,
) -> None:
    """Re-sync the calendar event on both providers after a race PATCH.

    ``scheduled_changed`` / ``metadata_changed`` compare pre- vs post-PATCH state
    and cannot be reconstructed from the DB, so the caller passes them in. Current
    id presence and qualification are read from the freshly loaded race.
    """
    async with async_session_maker() as session:
        race = (
            await session.execute(select(Race).where(Race.id == race_id).options(*_LOAD_OPTS))
        ).scalar_one_or_none()

        # No longer qualifies (or race gone): tear down whichever events exist.
        if race is None or not _qualifies(race):
            discord_id = race.discord_event_id if race else None
            malenia_id = race.malenia_event_id if race else None
            await delete_calendar_events(discord_event_id=discord_id, malenia_event_id=malenia_id)
            if race and (race.discord_event_id or race.malenia_event_id):
                race.discord_event_id = None
                race.malenia_event_id = None
                await session.commit()
            return

        # Qualifies from here on: _qualifies guarantees scheduled_at is set
        # (narrow it for mypy, which cannot see through the helper).
        assert race.scheduled_at is not None

        # Newly qualifies (no ids yet): create on both providers.
        if not race.discord_event_id and not race.malenia_event_id:
            await _create_on_providers(session, race)
            return

        # Existing events: patch only what changed.
        if scheduled_changed and race.discord_event_id:
            await update_scheduled_event(race.discord_event_id, scheduled_at=race.scheduled_at)
        if race.malenia_event_id and (scheduled_changed or metadata_changed):
            mode_display = format_pool_display_name(race.seed.pool if race.seed else None)
            await update_calendar_event(
                race.malenia_event_id,
                scheduled_at=race.scheduled_at if scheduled_changed else None,
                race_name=race.name if metadata_changed else None,
                mode_display=mode_display if metadata_changed else None,
                custom_rules=race.custom_rules if metadata_changed else None,
            )


async def delete_calendar_events(
    *,
    discord_event_id: str | None,
    malenia_event_id: str | None,
) -> None:
    """Delete the calendar event on whichever providers have an id."""
    if discord_event_id:
        await delete_scheduled_event(discord_event_id)
    if malenia_event_id:
        await delete_calendar_event(malenia_event_id)


async def add_calendar_participant(race_id: UUID, twitch_username: str) -> None:
    """Add a participant to the race's malenia event (no-op if there is no event)."""
    async with async_session_maker() as session:
        event_id = (
            await session.execute(select(Race.malenia_event_id).where(Race.id == race_id))
        ).scalar_one_or_none()
        if event_id:
            await add_event_participant(event_id, twitch_username)


async def remove_calendar_participant(race_id: UUID, twitch_username: str) -> None:
    """Remove a participant from the race's malenia event (no-op if there is no event)."""
    async with async_session_maker() as session:
        event_id = (
            await session.execute(select(Race.malenia_event_id).where(Race.id == race_id))
        ).scalar_one_or_none()
        if event_id:
            await remove_event_participant_by_login(event_id, twitch_username)
