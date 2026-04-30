"""Rewards service: grant, revoke, sync, equip, read."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import BadgeGrant, NameTemplateUnlock, RewardNotification
from speedfog_racing.rewards.catalog import BADGES, DEFAULT_TEMPLATE_ID, NAME_TEMPLATES


class UnknownRewardError(ValueError):
    pass


class LifecycleMismatchError(ValueError):
    pass


class RewardsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def grant_permanent_badge(
        self,
        user_id: uuid.UUID,
        badge_id: str,
        granted_by: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> BadgeGrant | None:
        badge = BADGES.get(badge_id)
        if badge is None:
            raise UnknownRewardError(f"Unknown badge_id={badge_id!r}")
        if badge.lifecycle != "permanent":
            raise LifecycleMismatchError(
                f"Badge {badge_id!r} is {badge.lifecycle}; use sync_transient_holders"
            )

        existing = await self.session.execute(
            select(BadgeGrant).where(
                BadgeGrant.user_id == user_id,
                BadgeGrant.badge_id == badge_id,
                BadgeGrant.revoked_at.is_(None),
            )
        )
        active = existing.scalar_one_or_none()
        if active is not None:
            return None

        grant = BadgeGrant(
            user_id=user_id,
            badge_id=badge_id,
            granted_by=granted_by,
            reason=reason,
        )
        self.session.add(grant)
        self.session.add(
            RewardNotification(
                user_id=user_id,
                kind="badge_granted",
                reward_id=badge_id,
            )
        )
        await self.session.flush()
        return grant

    async def grant_name_template(
        self,
        user_id: uuid.UUID,
        template_id: str,
        granted_by: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> NameTemplateUnlock | None:
        template = NAME_TEMPLATES.get(template_id)
        if template is None:
            raise UnknownRewardError(f"Unknown template_id={template_id!r}")
        if template_id == DEFAULT_TEMPLATE_ID:
            return None

        existing = await self.session.execute(
            select(NameTemplateUnlock).where(
                NameTemplateUnlock.user_id == user_id,
                NameTemplateUnlock.template_id == template_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        unlock = NameTemplateUnlock(
            user_id=user_id,
            template_id=template_id,
            granted_by=granted_by,
            reason=reason,
        )
        self.session.add(unlock)
        self.session.add(
            RewardNotification(
                user_id=user_id,
                kind="name_template_unlocked",
                reward_id=template_id,
            )
        )
        await self.session.flush()
        return unlock
