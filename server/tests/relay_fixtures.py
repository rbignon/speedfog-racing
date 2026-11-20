"""Relay race fixtures: a relay seed, and a relay race with its teams inserted directly.

Shared by the relay tests, on the model of ``event_fixtures.py``. Rows are
inserted without going through the routes, so a test of the rules does not
depend on the routes that build teams.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, Race, RelayTeam, Seed, User

RELAY_BLOCK = {
    "lock_flag": 1050290500,
    "chapel_warp_flag": 1050290501,
    "warp_flag_base": 1050290510,
    "zone_flag_base": 1050294000,
    "warp_flag_count": 490,
}


def relay_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``graph`` with the relay block added."""
    out = deepcopy(graph)
    out["relay"] = dict(RELAY_BLOCK)
    return out


async def make_relay_seed(db: AsyncSession, *, suffix: str, total_layers: int = 12) -> Seed:
    graph = relay_graph({"total_layers": total_layers, "nodes": []})
    seed = Seed(
        seed_number=f"relay_{suffix}",
        pool_name="standard",
        graph_json=graph,
        relay=True,
        total_layers=total_layers,
        folder_path=f"/test/relay_{suffix}",
    )
    db.add(seed)
    await db.flush()
    return seed


async def make_relay_race(
    db: AsyncSession,
    organizer: User,
    *,
    team_size: int = 3,
    teams: Sequence[Sequence[User]],
) -> Race:
    """A relay race with one team per inner list, members in order (the first is
    the team's first runner). An empty list makes an empty placeholder team."""
    seed = await make_relay_seed(db, suffix=f"race_{organizer.twitch_id}_{len(teams)}")
    race = Race(
        name="Relay",
        organizer_id=organizer.id,
        seed_id=seed.id,
        relay_team_size=team_size,
    )
    db.add(race)
    await db.flush()
    for index, users in enumerate(teams):
        team = RelayTeam(
            race_id=race.id,
            name=f"Team {index + 1}",
            color_index=index,
            placeholder=not users,
        )
        db.add(team)
        await db.flush()
        for user in users:
            member = Participant(
                race_id=race.id, user_id=user.id, relay_team_id=team.id, color_index=index
            )
            db.add(member)
            await db.flush()
            if team.first_runner_id is None:
                team.first_runner_id = member.id
    await db.commit()
    loaded = await db.execute(
        select(Race)
        .where(Race.id == race.id)
        .options(selectinload(Race.participants))
        .execution_options(populate_existing=True)
    )
    return loaded.scalar_one()
