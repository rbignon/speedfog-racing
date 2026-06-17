"""Static catalog of badges and name templates available in the system.

Adding an entry here is the only path to introduce a new reward.
Icons live under web/static/badges/ and must be deployed alongside any new badge.
"""

from typing import Final

from speedfog_racing.rewards.models_data import Badge, NameTemplate, PhantomSkin

VETERAN_RACE_THRESHOLD: Final = 25
DAILY_STREAK_REWARD_THRESHOLD: Final = 14

BADGES: dict[str, Badge] = {
    "early_adopter": Badge(
        id="early_adopter",
        name="Early Adopter",
        description="Account created before April 1st 2026.",
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
    "veteran": Badge(
        id="veteran",
        name="Veteran",
        description=f"Granted after finishing {VETERAN_RACE_THRESHOLD} races.",
        icon_filename="veteran.svg",
        lifecycle="permanent",
        sort_order=30,
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
    "frog": Badge(
        id="frog",
        name="Frog",
        description="Granted after finishing your first race.",
        icon_filename="frog.svg",
        lifecycle="permanent",
        sort_order=5,
    ),
}

DEFAULT_TEMPLATE_ID: Final = "default"
DEFAULT_PHANTOM_SKIN_ID: Final = "none"

NAME_TEMPLATES: dict[str, NameTemplate] = {
    "default": NameTemplate(
        id="default",
        name="Default",
        description="Standard white name.",
        color="#FFFFFF",
        sort_order=0,
    ),
    "speedfrog": NameTemplate(
        id="speedfrog",
        name="Speedfrog",
        description="Granted after finishing your first race.",
        gradient=("#A8E9B8", "#3E9E5C"),
        name_css="font-weight: 600; text-shadow: 0 0 4px rgba(62, 158, 92, 0.28);",
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%, rgba(62, 158, 92, 0.18), transparent 70%)"
        ),
        sort_order=5,
    ),
    "elo_crown": NameTemplate(
        id="elo_crown",
        name="ELO Crown",
        description="Granted permanently the first time you reach top 1 ELO.",
        gradient=("#FFE9A8", "#C8A44E"),
        name_css=(
            "font-style: italic; font-weight: 600; text-shadow: 0 0 4px rgba(168, 139, 92, 0.28);"
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
        name_css=(
            "font-style: italic; font-weight: 600; text-shadow: 0 0 5px rgba(184, 197, 214, 0.28);"
        ),
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%,"
            " rgba(184, 197, 214, 0.14), transparent 70%)"
        ),
        sort_order=20,
    ),
    "pioneer": NameTemplate(
        id="pioneer",
        name="Pioneer",
        description="Granted to accounts created before April 1st 2026.",
        name_css=(
            'font-family: Georgia, "Times New Roman", Times, serif;'
            " font-style: italic;"
            " font-weight: 600;"
            " letter-spacing: 0.02em;"
            " text-shadow: 0 0 6px rgba(200, 164, 78, 0.35);"
        ),
        background_css=(
            "radial-gradient(ellipse 50% 80% at 25% 50%,"
            " rgba(232, 220, 196, 0.12), transparent 60%)"
        ),
        sort_order=30,
    ),
    "weathered": NameTemplate(
        id="weathered",
        name="Weathered",
        description="Granted to veteran racers as a souvenir of their tenure.",
        gradient=("#D4A574", "#A06A35"),
        name_css=(
            "font-weight: 500;"
            " letter-spacing: 0.02em;"
            " text-shadow: 0 0 4px rgba(160, 106, 53, 0.28);"
        ),
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%,"
            " rgba(160, 106, 53, 0.14), transparent 70%)"
        ),
        sort_order=35,
    ),
    "archon": NameTemplate(
        id="archon",
        name="Archon",
        description="Reserved for platform administrators.",
        gradient=("#C4B5FD", "#7C3AED"),
        name_css=(
            'font-family: ui-monospace, "SF Mono", Menlo, Consolas,'
            ' "Courier New", monospace;'
            " font-weight: 600;"
            " text-shadow: 0 0 6px rgba(124, 58, 237, 0.35);"
        ),
        background_css=(
            "radial-gradient(ellipse 60% 100% at 25% 50%,"
            " rgba(124, 58, 237, 0.18), transparent 70%)"
        ),
        sort_order=40,
    ),
}

PHANTOM_SKINS: dict[str, PhantomSkin] = {
    "none": PhantomSkin(
        id="none",
        name="None",
        description="No phantom aura.",
        screenshot_filename="none.jpg",
        sort_order=0,
    ),
    "gold-aura": PhantomSkin(
        id="gold-aura",
        name="Gold Aura",
        description="Granted the first time you reach top 1 ELO.",
        screenshot_filename="gold-aura.jpg",
        sort_order=10,
    ),
    "silver-aura": PhantomSkin(
        id="silver-aura",
        name="Silver Aura",
        description="Granted the first time you enter the top 5 ELO.",
        screenshot_filename="silver-aura.jpg",
        sort_order=20,
    ),
    "cyan-aura": PhantomSkin(
        id="cyan-aura",
        name="Cyan Aura",
        description="Granted the first time you finish the week as Daily Champion.",
        screenshot_filename="cyan-aura.jpg",
        sort_order=30,
    ),
    "molten-aura": PhantomSkin(
        id="molten-aura",
        name="Molten Aura",
        description=(
            f"Granted the first time you reach a {DAILY_STREAK_REWARD_THRESHOLD}-day daily streak."
        ),
        screenshot_filename="molten-aura.jpg",
        sort_order=35,
    ),
    "emerald-aura": PhantomSkin(
        id="emerald-aura",
        name="Emerald Aura",
        description="Granted to accounts created before April 1st 2026.",
        screenshot_filename="emerald-aura.jpg",
        sort_order=40,
        obtainable=False,
    ),
    "crimson-aura": PhantomSkin(
        id="crimson-aura",
        name="Crimson Aura",
        description="Granted to veteran racers.",
        screenshot_filename="crimson-aura.jpg",
        sort_order=50,
    ),
    "violet-aura": PhantomSkin(
        id="violet-aura",
        name="Violet Aura",
        description="Special events reward.",
        screenshot_filename="violet-aura.jpg",
        sort_order=60,
    ),
}
