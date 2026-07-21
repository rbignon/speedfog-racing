"""Version parsing and mod compatibility decisions.

The wire-protocol version is decoupled from release numbers: it only moves
when the protocol itself changes (breaking change -> major + 1, compatible
addition worth signalling -> minor + 1). Release versions are for humans and
for the emergency `min_mod_version` gate.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def parse_version(value: str | None) -> tuple[int, ...] | None:
    """Parse leading dotted integer segments ("1.17.0" -> (1, 17, 0)).

    Returns None when the value is absent or has no leading numeric segment.
    Trailing non-numeric segments are ignored ("1.2.0-rc1" -> (1, 2)).

    The web has its own comparator (web/src/lib/utils/version.ts) with one
    deliberate difference: the release-gate comparison here treats a missing
    segment as older ((1, 18) < (1, 18, 0)), while the web pads with zeros
    ("1.18" == "1.18.0"). Keep any other semantic change in sync between the
    two.
    """
    if not value:
        return None
    parts: list[int] = []
    for segment in value.strip().split("."):
        if not segment.isdigit():
            break
        parts.append(int(segment))
    return tuple(parts) if parts else None


@dataclass(frozen=True)
class ModCompat:
    """Outcome of the auth-time compatibility decision."""

    reject_reason: str | None = None


def evaluate_mod_compat(
    client_protocol: str | None,
    client_release: str | None,
    *,
    server_protocol: str,
    min_release: str | None,
) -> ModCompat:
    """Decide what to do with a connecting mod.

    An absent or unparsable client protocol is assumed to be "1.0":
    pre-versioning builds speak protocol 1.0 by definition. A different
    protocol major (either direction) means the wire formats are
    incompatible and the connection must be rejected. The release-based
    `min_release` gate exists for non-protocol emergencies only.

    A same-major, older-minor client is accepted silently. Mods are
    distributed inside seed packs, so a player has no "update the mod"
    action to take; prompting them would be noise. The minor lag stays
    available as compatibility metadata (logged at auth, usable for
    capability gating), it just never reaches the player.
    """
    server = parse_version(server_protocol)
    if server is None:
        raise ValueError(f"Invalid server protocol version: {server_protocol!r}")
    s_major = server[0]
    client = parse_version(client_protocol) or (1, 0)
    c_major = client[0]
    c_minor = client[1] if len(client) > 1 else 0

    if c_major != s_major:
        return ModCompat(
            reject_reason=(
                f"Mod protocol v{c_major}.{c_minor} is not compatible with server "
                f"protocol v{server_protocol}. Re-download your seed pack."
            )
        )

    if min_release is not None:
        minimum = parse_version(min_release)
        if minimum is None:
            # The emergency gate is exactly the setting an operator reaches for
            # during an incident; a typo silently disabling it must be visible.
            logger.warning(
                "min_mod_version %r is not a parsable version; the release gate is disabled",
                min_release,
            )
        release = parse_version(client_release)
        if minimum is not None and (release is None or release < minimum):
            return ModCompat(
                reject_reason=(
                    f"Mod v{client_release or 'unknown'} is no longer supported "
                    f"(minimum v{min_release}). Re-download your seed pack."
                )
            )

    return ModCompat()
