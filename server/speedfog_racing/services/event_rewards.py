"""Event rewards: which catalog entries a bracket's config names, who gets them, the grant.

The config schema checks the shape of a reward block only; the catalog is
consulted here, when an admin saves an event, so a later catalog change never
invalidates a stored config.

A reward block is one bracket and one role: its seated runners, or its
champion. The recipients come from the pipeline the public event page runs
(ladder, draw, walkovers, stage results), and the organizer grants one block
at a time, once it can no longer change.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    BadgeGrant,
    Event,
    NameTemplateUnlock,
    PhantomSkinUnlock,
    RaceStatus,
    User,
)
from speedfog_racing.rewards.catalog import (
    BADGES,
    DEFAULT_TEMPLATE_ID,
    NAME_TEMPLATES,
    PHANTOM_SKINS,
)
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.schemas import EventConfig, EventRewardSet
from speedfog_racing.services.event_service import (
    announce_date,
    apply_walkovers,
    bracket_draw,
    compute_ladder,
    compute_qualified,
    count_finished_before,
    newcomer_flags,
    resolve_stages,
    resolve_withdrawn,
)

RewardKind = Literal["badge", "name_template", "phantom_skin"]
RewardRole = Literal["seated", "champion"]
# Why a block cannot be granted yet: the ladder still moves, the draw has not
# locked, the closing stage is still being played, or it ended without a runner.
WaitingReason = Literal["ladder_provisional", "draw_not_locked", "stage_incomplete", "no_champion"]

# The reward tables' ``reason`` column is ``String(200)``.
_REASON_MAX = 200


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


# --- blocks -----------------------------------------------------------------


@dataclass(frozen=True)
class RewardBlock:
    """One bracket's rewards for one role, and who they go to."""

    bracket_key: str
    bracket_label: str
    role: RewardRole
    # The ids the catalog can grant, in ``reward_refs`` order.
    rewards: list[RewardRef]
    # The ids it refuses (see ``grant_error``): listed, never granted.
    unknown: list[RewardRef]
    waiting: WaitingReason | None
    # Seed order for the seated runners; empty while waiting.
    recipients: list[User]
    # Banned users the block would otherwise reward: never granted anything.
    banned: list[User]


async def compute_reward_blocks(db: AsyncSession, event: Event, now: datetime) -> list[RewardBlock]:
    """Every bracket's reward blocks at ``now``, bracket order, the seated before the champion.

    ``event`` comes from ``load_event``; a stored config that no longer
    validates raises ``pydantic.ValidationError``. A role whose reward set
    names no id has no block. The seated runners are the bracket's draw,
    a forfeit included (they did qualify), a withdrawal not; they wait for a
    final ladder and for ``draw_locks_at``. The champion is the first entry of
    the bracket's closing stage once that stage is complete. Signups are left
    out of the ladder: a runner without a qualifier run holds no seat.
    """
    config = EventConfig.model_validate(event.config)
    resolved = resolve_stages(event, config, now)
    users: dict[UUID, User] = {p.user_id: p.user for race in event.races for p in race.participants}
    users.update({s.user_id: s.user for s in event.signups})
    struck = resolve_withdrawn(config.withdrawn, users)
    ladder = compute_ladder(config.mode_keys(), resolved.qualifier, struck=struck)
    finished_before = await count_finished_before(db, set(users), announce_date(event, config))
    newcomers = newcomer_flags(finished_before, event.newcomer_threshold, users.keys())
    ladder_final = bool(resolved.qualifier) and all(
        r.status == RaceStatus.FINISHED for _, r in resolved.qualifier
    )
    forfeits = resolve_withdrawn(config.forfeits, users)
    qualified = compute_qualified(ladder, config, newcomers, ladder_final, forfeits)
    apply_walkovers(config, resolved, qualified, forfeits)

    seated_waiting: WaitingReason | None = None
    if not ladder_final:
        seated_waiting = "ladder_provisional"
    elif config.draw_locks_at is not None and now < config.draw_locks_at:
        seated_waiting = "draw_not_locked"

    blocks: list[RewardBlock] = []
    for bracket, seated in bracket_draw(config, qualified):
        if bracket.rewards is None:
            continue
        roles: tuple[tuple[RewardRole, EventRewardSet | None], ...] = (
            ("seated", bracket.rewards.seated),
            ("champion", bracket.rewards.champion),
        )
        for role, rewards in roles:
            refs = reward_refs(rewards) if rewards is not None else []
            if not refs:
                continue
            waiting: WaitingReason | None
            if role == "seated":
                waiting, chosen = seated_waiting, seated
            else:
                result = resolved.results[bracket.closing_stage().key]
                if not result.complete:
                    waiting, chosen = "stage_incomplete", []
                elif not result.entries:
                    waiting, chosen = "no_champion", []
                else:
                    waiting, chosen = None, [result.entries[0].user_id]
            candidates = [users[u] for u in chosen if u in users] if waiting is None else []
            blocks.append(
                RewardBlock(
                    bracket_key=bracket.key,
                    bracket_label=bracket.label,
                    role=role,
                    rewards=[r for r in refs if grant_error(r) is None],
                    unknown=[r for r in refs if grant_error(r) is not None],
                    waiting=waiting,
                    recipients=[u for u in candidates if u.banned_at is None],
                    banned=[u for u in candidates if u.banned_at is not None],
                )
            )
    return blocks


async def owned_refs(
    db: AsyncSession, user_ids: Collection[UUID], refs: Sequence[RewardRef]
) -> dict[UUID, set[str]]:
    """Each user's ``RewardRef.ref`` among ``refs`` they already own.

    A badge counts while its grant is not revoked. A user owning none of
    ``refs`` may be absent.
    """
    badges = [r.id for r in refs if r.kind == "badge"]
    templates = [r.id for r in refs if r.kind == "name_template"]
    skins = [r.id for r in refs if r.kind == "phantom_skin"]
    owned: dict[UUID, set[str]] = {}
    if not user_ids:
        return owned
    if badges:
        rows = await db.execute(
            select(BadgeGrant.user_id, BadgeGrant.badge_id).where(
                BadgeGrant.user_id.in_(user_ids),
                BadgeGrant.badge_id.in_(badges),
                BadgeGrant.revoked_at.is_(None),
            )
        )
        for user_id, badge_id in rows.all():
            owned.setdefault(user_id, set()).add(RewardRef("badge", badge_id).ref)
    if templates:
        rows = await db.execute(
            select(NameTemplateUnlock.user_id, NameTemplateUnlock.template_id).where(
                NameTemplateUnlock.user_id.in_(user_ids),
                NameTemplateUnlock.template_id.in_(templates),
            )
        )
        for user_id, template_id in rows.all():
            owned.setdefault(user_id, set()).add(RewardRef("name_template", template_id).ref)
    if skins:
        rows = await db.execute(
            select(PhantomSkinUnlock.user_id, PhantomSkinUnlock.skin_id).where(
                PhantomSkinUnlock.user_id.in_(user_ids),
                PhantomSkinUnlock.skin_id.in_(skins),
            )
        )
        for user_id, skin_id in rows.all():
            owned.setdefault(user_id, set()).add(RewardRef("phantom_skin", skin_id).ref)
    return owned


def grant_reason(event_name: str, block: RewardBlock) -> str:
    """The reason a block's grants record, cut to fit the column."""
    title = "qualifier" if block.role == "seated" else "champion"
    return f"{event_name}: {block.bracket_label} {title}"[:_REASON_MAX]


async def grant_reward_block(
    db: AsyncSession, event_name: str, block: RewardBlock, granted_by: UUID
) -> int:
    """Grant every reward of ``block`` to each of its recipients; how many were new.

    A reward a recipient already owns is skipped, without a notification. The
    unknown ids stay out. Grants unlock only: nothing gets equipped. The caller
    commits, and grants only a block that is not waiting.
    """
    assert block.waiting is None, "a waiting block has no recipients to grant"
    service = RewardsService(db)
    reason = grant_reason(event_name, block)
    created = 0
    for user in block.recipients:
        for ref in block.rewards:
            grant: BadgeGrant | NameTemplateUnlock | PhantomSkinUnlock | None
            if ref.kind == "badge":
                grant = await service.grant_permanent_badge(
                    user.id, ref.id, granted_by=granted_by, reason=reason
                )
            elif ref.kind == "name_template":
                grant = await service.grant_name_template(
                    user.id, ref.id, granted_by=granted_by, reason=reason
                )
            else:
                grant = await service.grant_phantom_skin(
                    user.id, ref.id, granted_by=granted_by, reason=reason
                )
            if grant is not None:
                created += 1
    return created
