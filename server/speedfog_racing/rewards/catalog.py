"""Static catalog of badges and name templates available in the system.

Adding an entry here is the only path to introduce a new reward.
Icons live under web/static/badges/ and must be deployed alongside any new badge.
"""

from typing import Final

from speedfog_racing.rewards.models_data import Badge, NameTemplate

BADGES: dict[str, Badge] = {
    "early_adopter": Badge(
        id="early_adopter",
        name="Early Adopter",
        description="Account created before the rewards system launched.",
        icon_filename="early_adopter.svg",
        lifecycle="permanent",
        sort_order=10,
    ),
    "contributor": Badge(
        id="contributor",
        name="Contributor",
        description="Helped improve SpeedFog Racing.",
        icon_filename="contributor.svg",
        lifecycle="permanent",
        sort_order=20,
    ),
    "top1_elo": Badge(
        id="top1_elo",
        name="ELO Champion",
        description="Currently holds the highest ELO rating.",
        icon_filename="top1_elo.svg",
        lifecycle="transient",
        sort_order=1,
    ),
    "weekly_daily_champion": Badge(
        id="weekly_daily_champion",
        name="Daily Champion",
        description="Won the most daily seeds last week.",
        icon_filename="weekly_daily_champion.svg",
        lifecycle="transient",
        sort_order=2,
    ),
}

DEFAULT_TEMPLATE_ID: Final = "default"

NAME_TEMPLATES: dict[str, NameTemplate] = {
    "default": NameTemplate(
        id="default",
        name="Default",
        description="Standard white name.",
        color="#FFFFFF",
        sort_order=0,
    ),
    "elo_crown": NameTemplate(
        id="elo_crown",
        name="ELO Crown",
        description="Granted permanently the first time you reach top 1 ELO.",
        gradient=("#FFFFFF", "#FFD700"),
        background_css="linear-gradient(90deg, rgba(255,255,255,0.10), rgba(255,215,0,0.06))",
        sort_order=10,
    ),
}
