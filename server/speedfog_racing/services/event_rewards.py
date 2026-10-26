"""Event rewards: which catalog entries a bracket's config names, and whether they can be granted.

The config schema checks the shape of a reward block only; the catalog is
consulted here, when an admin saves an event, so a later catalog change never
invalidates a stored config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from speedfog_racing.rewards.catalog import (
    BADGES,
    DEFAULT_TEMPLATE_ID,
    NAME_TEMPLATES,
    PHANTOM_SKINS,
)
from speedfog_racing.schemas import EventConfig, EventRewardSet

RewardKind = Literal["badge", "name_template", "phantom_skin"]
RewardRole = Literal["seated", "champion"]


@dataclass(frozen=True)
class RewardRef:
    kind: RewardKind
    id: str

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.id}"


def reward_refs(rewards: EventRewardSet) -> list[RewardRef]:
    """Name templates, then badges, then phantom skins, each in list order."""
    return [
        *(RewardRef("name_template", i) for i in rewards.name_templates),
        *(RewardRef("badge", i) for i in rewards.badges),
        *(RewardRef("phantom_skin", i) for i in rewards.phantom_skins),
    ]


def grant_error(ref: RewardRef) -> str | None:
    """Why the catalog cannot grant ``ref``, or None when it can."""
    if ref.kind == "badge":
        badge = BADGES.get(ref.id)
        if badge is None:
            return "unknown"
        return None if badge.lifecycle == "permanent" else "transient badge"
    if ref.kind == "name_template":
        if ref.id not in NAME_TEMPLATES:
            return "unknown"
        return "default template" if ref.id == DEFAULT_TEMPLATE_ID else None
    skin = PHANTOM_SKINS.get(ref.id)
    if skin is None:
        return "unknown"
    return "pseudo skin" if skin.pseudo else None


_FIELD_OF_KIND: dict[RewardKind, str] = {
    "name_template": "name_templates",
    "badge": "badges",
    "phantom_skin": "phantom_skins",
}


def reward_catalog_errors(config: EventConfig) -> list[str]:
    """One line per reward id of ``config`` the catalog cannot grant."""
    errors: list[str] = []
    for i, bracket in enumerate(config.brackets):
        if bracket.rewards is None:
            continue
        roles: tuple[tuple[RewardRole, EventRewardSet | None], ...] = (
            ("seated", bracket.rewards.seated),
            ("champion", bracket.rewards.champion),
        )
        for role, rewards in roles:
            if rewards is None:
                continue
            for ref in reward_refs(rewards):
                error = grant_error(ref)
                if error is not None:
                    field = _FIELD_OF_KIND[ref.kind]
                    errors.append(f"brackets.{i}.rewards.{role}.{field}: {error} {ref.id!r}")
    return errors
