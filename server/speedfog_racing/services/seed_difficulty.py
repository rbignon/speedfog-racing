"""Seed difficulty scoring from graph structure."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Type weights: how much each node type contributes relative to a legacy dungeon.
# Bosses produce more deaths, so they weigh more.
NODE_TYPE_WEIGHT: dict[str, float] = {
    "legacy_dungeon": 1.0,
    "mini_dungeon": 0.7,
    "boss_arena": 1.5,
    "major_boss": 2.0,
    "final_boss": 2.5,
}

# Tier exponent: captures the non-linear difficulty scaling in Elden Ring.
TIER_EXPONENT = 1.3


def compute_seed_difficulty(graph_json: dict[str, Any]) -> float:
    """Compute an intrinsic difficulty score from a seed's graph structure.

    Score = sum over non-start nodes of: type_weight * tier^TIER_EXPONENT.
    """
    score = 0.0
    for node in graph_json.get("nodes", {}).values():
        node_type = node.get("type", "")
        if node_type == "start":
            continue
        weight = NODE_TYPE_WEIGHT.get(node_type, 1.0)
        tier = node.get("tier", 1)
        score += weight * (tier**TIER_EXPONENT)
    return score


async def backfill_difficulty_scores(db: AsyncSession) -> int:
    """Recompute difficulty_score for seeds that have score=0.

    Returns the number of seeds updated.
    """
    from speedfog_racing.models import Seed

    result = await db.execute(select(Seed).where(Seed.difficulty_score == 0.0))
    seeds = result.scalars().all()
    count = 0
    for seed in seeds:
        score = compute_seed_difficulty(seed.graph_json)
        if score > 0:
            seed.difficulty_score = score
            count += 1
    if count > 0:
        await db.commit()
        logger.info("Backfilled difficulty_score for %d seeds", count)
    return count
