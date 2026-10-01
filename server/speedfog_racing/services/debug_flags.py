"""Game debug flags reported by the mod (cheat detection).

During a race the mod reads the game's debug-menu switch bytes (one shot,
no death, infinite stamina, ...) that the practice tool and TarnishedTool
toggle, and sends the names it saw since the race start with every
status_update. Each participant keeps the first observation of every flag.
See docs/CHEAT_DETECTION.md.
"""

from datetime import datetime
from typing import Any

# Wire names, one per watched byte. Keep in sync with DEBUG_FLAGS in
# mod/src/core/debug_flags.rs and the labels in web/src/lib/debugFlags.ts.
DEBUG_FLAG_NAMES = frozenset(
    {
        "player_no_death",
        "torrent_no_death",
        "one_shot",
        "infinite_consumables",
        "infinite_stamina",
        "infinite_fp",
        "infinite_arrows",
        "hidden",
        "silent",
        "all_no_death",
        "all_no_damage",
        "all_no_hit",
        "all_no_attack",
        "all_no_move",
        "all_no_ai",
        "infinite_aow_fp",
    }
)

# A report names each flag at most once. The cap leaves room for flags a
# newer mod knows and this server does not; anything longer is malformed.
MAX_REPORTED_FLAGS = 64


def merge_debug_flags(
    existing: dict[str, dict[str, Any]] | None,
    reported: object,
    *,
    igt_ms: int,
    node_id: str | None,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]] | None, list[str]]:
    """Add the first observation of each newly reported flag.

    ``reported`` is the raw ``debug_flags`` value of a status_update.
    Anything that is not a list of at most ``MAX_REPORTED_FLAGS`` entries is
    ignored, as are entries that are not known flag names: a malformed report
    never rejects the update it rides on. Returns the merged map (``existing``
    itself when nothing is new) and the newly added names, sorted.
    """
    if not isinstance(reported, list) or len(reported) > MAX_REPORTED_FLAGS:
        return existing, []
    current = existing or {}
    added = sorted(
        {
            name
            for name in reported
            if isinstance(name, str) and name in DEBUG_FLAG_NAMES and name not in current
        }
    )
    if not added:
        return existing, []
    merged = dict(current)
    for name in added:
        merged[name] = {"igt_ms": igt_ms, "node_id": node_id, "detected_at": now.isoformat()}
    return merged, added


# Race roles that may see a race's detections (see services.chat_access.race_role).
_STAFF_ROLES = frozenset({"organizer", "admin"})


def can_see_debug_flags(role: str | None) -> bool:
    """True when a race role may see the race's cheat detections."""
    return role in _STAFF_ROLES
