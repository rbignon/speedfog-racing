"""Application configuration using Pydantic settings."""

from datetime import UTC, datetime

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Race items: each tier (front, middle, back) maps its base item keys to a draw
# weight (an item can sit in several tiers; 0 or absent = not drawn).
DEFAULT_RACE_ITEMS_TIER_WEIGHTS: dict[str, dict[str, int]] = {
    "front": {"rune_pouch": 1, "banana": 1, "mushroom": 1, "giant": 1},
    "middle": {
        "shield": 1,
        "mushroom": 1,
        "red_shell": 1,
        "hammer": 1,
        "ink": 1,
        "vanish": 1,
        "slow_mo": 1,
        "camera": 1,
        "talisman_thief": 1,
        "toxic_blossom": 1,
        "junk_weapon": 1,
    },
    "back": {
        "red_shell": 1,
        "blue_shell": 1,
        "lightning": 1,
        "flask_stopper": 1,
        "toxic_blossom": 1,
        "star": 1,
        "vanish": 1,
        "unseen_foes": 1,
        "slow_mo": 1,
        "camera": 1,
        "talisman_thief": 1,
        "hammer": 1,
        "hunter": 1,
    },
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://localhost/speedfog_racing"

    # Twitch OAuth
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    # App
    secret_key: str
    oauth_redirect_url: str = "http://localhost:5173/auth/callback"  # Where to redirect after OAuth
    websocket_url: str = "ws://localhost:8000"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]

    # i18n
    i18n_dir: str = "data/i18n"

    # Seeds
    seeds_pool_dir: str = "/data/seeds"
    # Mod DLL appended to every seed pack at download (deploy/deploy-mod.sh installs it)
    mod_dll_path: str = "/opt/speedfog-racing/mod/speedfog_racing.dll"
    speedfog_path: str = ""  # Path to speedfog repo for seed generation

    # OG images
    og_cache_dir: str = "~/.cache/speedfog-racing/og"

    # Discord integration (optional)
    discord_webhook_url: str | None = None
    discord_training_webhook_url: str | None = None
    discord_admin_webhook_url: str | None = None
    # Speedrun and Set Seed races, and speedrun records while the records webhook
    # is unset (main webhook when unset)
    discord_speedrun_webhook_url: str | None = None
    # Speedrun records (speedrun webhook, else main, when unset)
    discord_records_webhook_url: str | None = None
    base_url: str = "https://speedfog.racing"

    # Discord bot (optional, enables scheduled events + runner role)
    discord_bot_token: str | None = None
    discord_guild_id: str | None = None
    discord_runner_role_id: str | None = None
    discord_public_key: str | None = None
    discord_channel_id: str | None = None

    # events.malenia.win calendar (optional)
    malenia_api_token: str | None = None
    malenia_api_base: str = "https://events.malenia.win/api"

    # Race
    countdown_seconds: int = 10
    # IGT penalty (ms) a connected mod applies per detected quit-out; 0 disables.
    quit_out_penalty_ms: int = 2000
    # Race items: the tier weights (JSON in .env; a tier it leaves out keeps its
    # default, see _merge_tier_weights), and the damage curve of the two damage
    # items.
    race_items_tier_weights: dict[str, dict[str, int]] = DEFAULT_RACE_ITEMS_TIER_WEIGHTS
    race_items_banana_pct: int = 15
    race_items_red_shell_pct: int = 40
    # Shared by the damage items: the HP percent a hit lands at when the base
    # would go below it, and the flat damage once HP is under floor + tail.
    race_items_damage_floor_pct: int = 20
    race_items_damage_tail_pct: int = 10
    # The Hammer brings each target's equip load to this percent of its max
    # load (70 to 99 is a fat roll; clamped to 0..99). The other race item
    # percentages are clamped to 0..100 when sent to the mod.
    race_items_hammer_load_pct: int = 97
    # Slow-mo's speed percent of the target (clamped to 10..100); the
    # Lightning and the Giant scale the targets to these percents (clamped to
    # 25..300).
    race_items_slow_mo_speed_pct: int = 50
    race_items_lightning_scale_pct: int = 50
    race_items_giant_scale_pct: int = 150
    # Runners rank for race items (draw tier, targets) in leaderboard order, a
    # runner moving above one it leads by this many seconds of IGT at the same
    # point (gap_ms): time lost outside IGT (slow loads) can leave a runner
    # ahead in IGT on a shallower layer. 0 or less ranks by IGT alone (ties in
    # leaderboard order); a very large value keeps the leaderboard order.
    race_items_igt_lead_s: int = 60
    # Reject mods whose release version is older than this (emergency gate for
    # non-protocol issues, e.g. a crashing build). None disables the gate.
    min_mod_version: str | None = None
    # Relay races (docs/RELAY.md): off until the shipped mod speaks the relay
    # protocol. While off, creating one is refused and the pools report no
    # relay seed, which keeps the web's Relay format closed.
    relay_races_enabled: bool = False

    # Set Seed (docs/SPEEDRUN.md). Seeds added (scanned) before this instant
    # are not replayable (raised once per game patch); None disables the cutoff.
    set_seed_min_seed_date: datetime | None = None
    # The Speedrun boards count runs on seeds added (scanned) from this instant on;
    # older runs stay on their race and seed pages. Unlike the cutoff above, it is
    # not raised on a game patch.
    speedrun_board_start_date: datetime = datetime(2026, 9, 1, tzinfo=UTC)
    # How many of each category's best Set Seed seeds keep their files once discarded.
    set_seed_kept_top_seeds: int = 10
    # Seeds a player can protect from the purge at once.
    seed_protection_limit: int = 3
    # A discarded seed keeps its files this many days after its last race or session.
    seed_purge_grace_days: int = 30
    # Speedrun draws are refused when a pool has this many AVAILABLE seeds or fewer
    # (a pool's own Pool.speedrun_floor overrides it).
    speedrun_default_floor: int = 5
    # An ACTIVE Speedrun solo session older than this becomes ABANDONED.
    speedrun_session_ttl_hours: int = 24
    # A player with this many unfinished Speedrun solo sessions created within the window
    # below cannot start another (0 disables the limit).
    speedrun_solo_unfinished_limit: int = 3
    # Hours back the unfinished Speedrun solo sessions are counted.
    speedrun_solo_unfinished_window_hours: int = 24
    # Personal bests the Speedrun page's Recent PBs panel lists.
    speedrun_recent_runs_count: int = 5
    # Most practiced seeds panel of the Speedrun tab: how many seeds it lists...
    speedrun_practiced_seeds_count: int = 5
    # ...and how many days back their attempts are counted.
    speedrun_practiced_seeds_days: int = 7

    # Site-wide announcement shown as a banner on every web page (served via
    # /health so it can change without a frontend deploy). None hides it; the
    # optional URL adds a link, labelled "Read more" unless a link text is set.
    announcement: str | None = None
    announcement_url: str | None = None
    announcement_link_text: str | None = None

    # Server
    log_level: str = "INFO"
    log_json: bool = False
    # Net allocations of GC-tracked objects between two young collections for
    # the server's lifetime (services/loop_monitor.py, ``tuned_gc``); 0 keeps
    # the interpreter's defaults.
    gc_gen0_threshold: int = 50_000

    # Sentry
    sentry_dsn: str = ""
    sentry_environment: str = "production"

    @field_validator("race_items_tier_weights")
    @classmethod
    def _merge_tier_weights(cls, value: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """Lay the configured tiers over the default table, so a tier the
        table leaves out keeps its default weights. An unknown tier or a
        negative weight refuses the settings (the server does not start):
        either would leave a tier granting less than meant without a word.
        Unknown item keys are only warned about, at startup (``main.py``):
        the item rules import these settings."""
        unknown = sorted(set(value) - set(DEFAULT_RACE_ITEMS_TIER_WEIGHTS))
        if unknown:
            raise ValueError(
                f"unknown tier(s) {', '.join(unknown)}: the tiers are "
                f"{', '.join(DEFAULT_RACE_ITEMS_TIER_WEIGHTS)}"
            )
        negative = sorted(
            f"{tier}.{key}"
            for tier, weights in value.items()
            for key, weight in weights.items()
            if weight < 0
        )
        if negative:
            raise ValueError(f"negative weight(s) for {', '.join(negative)}: use 0 to never draw")
        merged = {tier: dict(weights) for tier, weights in DEFAULT_RACE_ITEMS_TIER_WEIGHTS.items()}
        merged.update(value)
        return merged


settings = Settings()  # type: ignore[call-arg]  # populated from env vars / .env file
