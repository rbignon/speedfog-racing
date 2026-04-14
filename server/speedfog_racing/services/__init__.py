"""Business logic services."""

from speedfog_racing.services.pool_service import (
    get_pool,
    list_pools,
    set_pool_enabled,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.services.seed_pack_service import (
    generate_player_config,
    stream_seed_pack_with_config,
)
from speedfog_racing.services.seed_service import (
    assign_seed_to_race,
    discard_pool,
    get_available_seed,
    get_pool_config,
    get_pool_stats,
    reroll_seed_for_race,
    scan_pool,
)
from speedfog_racing.services.training_service import (
    create_training_session,
    get_played_seed_counts,
    get_training_seed,
)

__all__ = [
    "check_race_auto_finish",
    "assign_seed_to_race",
    "discard_pool",
    "generate_player_config",
    "stream_seed_pack_with_config",
    "get_available_seed",
    "get_pool",
    "get_pool_config",
    "get_pool_stats",
    "list_pools",
    "reroll_seed_for_race",
    "scan_pool",
    "set_pool_enabled",
    "create_training_session",
    "get_played_seed_counts",
    "get_training_seed",
]
