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
        gradient=("#FFE9A8", "#C8A44E"),
        name_css=(
            'font-family: Georgia, "Times New Roman", Times, serif;'
            " font-style: italic;"
            " letter-spacing: 0.02em;"
            " text-shadow: 0 0 6px rgba(200, 164, 78, 0.35);"
        ),
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%,"
            " rgba(200, 164, 78, 0.18), transparent 70%)"
        ),
        sort_order=10,
    ),
    "runebearer": NameTemplate(
        id="runebearer",
        name="Runebearer",
        description="Granted permanently the first time you enter the top 5 ELO.",
        gradient=("#B8C5D6", "#6F87A6"),
        name_css="font-style: italic; text-shadow: 0 0 5px rgba(184, 197, 214, 0.28);",
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%,"
            " rgba(184, 197, 214, 0.14), transparent 70%)"
        ),
        sort_order=20,
    ),
}
