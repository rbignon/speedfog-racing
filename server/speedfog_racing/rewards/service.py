"""Rewards service: grant, revoke, sync, equip, read."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    Participant,
    ParticipantStatus,
    PhantomSkinUnlock,
    RewardNotification,
    User,
)
from speedfog_racing.rewards.catalog import (
    BADGES,
    DAILY_STREAK_REWARD_THRESHOLD,
    DEFAULT_PHANTOM_SKIN_ID,
    DEFAULT_TEMPLATE_ID,
    NAME_TEMPLATES,
    PHANTOM_SKINS,
    VETERAN_RACE_THRESHOLD,
)
from speedfog_racing.rewards.models_data import Badge, NameTemplate, PhantomSkin
from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD


class UnknownRewardError(ValueError):
    pass


class LifecycleMismatchError(ValueError):
    pass


class NotOwnedError(ValueError):
    pass


@dataclass
class SyncResult:
    granted: set[uuid.UUID]
    revoked: set[uuid.UUID]


@dataclass
class Inventory:
    held_badges: list[Badge]
    unlocked_templates: list[NameTemplate]
    unlocked_phantom_skins: list[PhantomSkin]
    equipped_badge_id: str | None
    equipped_name_template_id: str | None
    equipped_phantom_skin_id: str | None


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

    async def grant_phantom_skin(
        self,
        user_id: uuid.UUID,
        skin_id: str,
        granted_by: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> PhantomSkinUnlock | None:
        skin = PHANTOM_SKINS.get(skin_id)
        if skin is None:
            raise UnknownRewardError(f"Unknown skin_id={skin_id!r}")
        if skin_id == DEFAULT_PHANTOM_SKIN_ID:
            return None

        existing = await self.session.execute(
            select(PhantomSkinUnlock).where(
                PhantomSkinUnlock.user_id == user_id,
                PhantomSkinUnlock.skin_id == skin_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        unlock = PhantomSkinUnlock(
            user_id=user_id,
            skin_id=skin_id,
            granted_by=granted_by,
            reason=reason,
        )
        self.session.add(unlock)
        self.session.add(
            RewardNotification(
                user_id=user_id,
                kind="phantom_skin_unlocked",
                reward_id=skin_id,
            )
        )
        await self.session.flush()
        return unlock

    async def sync_transient_holders(
        self,
        badge_id: str,
        new_holder_ids: set[uuid.UUID],
        reason: str | None = None,
    ) -> SyncResult:
        badge = BADGES.get(badge_id)
        if badge is None:
            raise UnknownRewardError(f"Unknown badge_id={badge_id!r}")
        if badge.lifecycle != "transient":
            raise LifecycleMismatchError(
                f"Badge {badge_id!r} is {badge.lifecycle}; use grant_permanent_badge"
            )

        current = await self.session.execute(
            select(BadgeGrant.user_id).where(
                BadgeGrant.badge_id == badge_id,
                BadgeGrant.revoked_at.is_(None),
            )
        )
        current_holders: set[uuid.UUID] = {row[0] for row in current.all()}

        to_revoke = current_holders - new_holder_ids
        to_grant = new_holder_ids - current_holders

        if to_revoke:
            await self.session.execute(
                update(BadgeGrant)
                .where(
                    BadgeGrant.badge_id == badge_id,
                    BadgeGrant.user_id.in_(to_revoke),
                    BadgeGrant.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await self.session.execute(
                update(User)
                .where(
                    User.id.in_(to_revoke),
                    User.equipped_badge_id == badge_id,
                )
                .values(equipped_badge_id=None)
            )
            for uid in to_revoke:
                self.session.add(
                    RewardNotification(user_id=uid, kind="badge_revoked", reward_id=badge_id)
                )

        for uid in to_grant:
            self.session.add(
                BadgeGrant(
                    user_id=uid,
                    badge_id=badge_id,
                    reason=reason,
                )
            )
            self.session.add(
                RewardNotification(user_id=uid, kind="badge_granted", reward_id=badge_id)
            )

        await self.session.flush()
        return SyncResult(granted=to_grant, revoked=to_revoke)

    async def set_equipped_badge(
        self,
        user_id: uuid.UUID,
        badge_id: str | None,
        *,
        enforce_ownership: bool = True,
    ) -> None:
        if badge_id is not None:
            if badge_id not in BADGES:
                raise UnknownRewardError(f"Unknown badge_id={badge_id!r}")
            if enforce_ownership:
                owned = await self.session.execute(
                    select(BadgeGrant).where(
                        BadgeGrant.user_id == user_id,
                        BadgeGrant.badge_id == badge_id,
                        BadgeGrant.revoked_at.is_(None),
                    )
                )
                if owned.scalar_one_or_none() is None:
                    raise NotOwnedError(f"User does not hold badge {badge_id!r}")

        await self.session.execute(
            update(User).where(User.id == user_id).values(equipped_badge_id=badge_id)
        )

    async def set_equipped_name_template(
        self,
        user_id: uuid.UUID,
        template_id: str | None,
        *,
        enforce_ownership: bool = True,
    ) -> None:
        target = template_id if template_id is not None else DEFAULT_TEMPLATE_ID
        if target not in NAME_TEMPLATES:
            raise UnknownRewardError(f"Unknown template_id={target!r}")
        if target != DEFAULT_TEMPLATE_ID and enforce_ownership:
            owned = await self.session.execute(
                select(NameTemplateUnlock).where(
                    NameTemplateUnlock.user_id == user_id,
                    NameTemplateUnlock.template_id == target,
                )
            )
            if owned.scalar_one_or_none() is None:
                raise NotOwnedError(f"User has not unlocked template {target!r}")

        await self.session.execute(
            update(User).where(User.id == user_id).values(equipped_name_template_id=target)
        )

    async def set_equipped_phantom_skin(
        self,
        user_id: uuid.UUID,
        skin_id: str | None,
        *,
        enforce_ownership: bool = True,
    ) -> None:
        if skin_id is not None and skin_id != DEFAULT_PHANTOM_SKIN_ID:
            if skin_id not in PHANTOM_SKINS:
                raise UnknownRewardError(f"Unknown skin_id={skin_id!r}")
            if enforce_ownership:
                owned = await self.session.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user_id,
                        PhantomSkinUnlock.skin_id == skin_id,
                    )
                )
                if owned.scalar_one_or_none() is None:
                    raise NotOwnedError(f"User has not unlocked skin {skin_id!r}")

        # "none" or None both clear the column to NULL.
        stored = None if skin_id is None or skin_id == DEFAULT_PHANTOM_SKIN_ID else skin_id
        await self.session.execute(
            update(User).where(User.id == user_id).values(equipped_phantom_skin_id=stored)
        )

    async def get_user_inventory(self, user_id: uuid.UUID) -> Inventory:
        held = await self.session.execute(
            select(BadgeGrant.badge_id).where(
                BadgeGrant.user_id == user_id, BadgeGrant.revoked_at.is_(None)
            )
        )
        held_ids = [row[0] for row in held.all()]
        held_badges = [BADGES[bid] for bid in held_ids if bid in BADGES]

        unlocks = await self.session.execute(
            select(NameTemplateUnlock.template_id).where(NameTemplateUnlock.user_id == user_id)
        )
        unlocked_ids: set[str] = {row[0] for row in unlocks.all()}
        unlocked_ids.add(DEFAULT_TEMPLATE_ID)
        unlocked_templates = [NAME_TEMPLATES[tid] for tid in unlocked_ids if tid in NAME_TEMPLATES]

        skin_unlocks = await self.session.execute(
            select(PhantomSkinUnlock.skin_id).where(PhantomSkinUnlock.user_id == user_id)
        )
        skin_ids: set[str] = {row[0] for row in skin_unlocks.all()}
        unlocked_skins = [PHANTOM_SKINS[sid] for sid in skin_ids if sid in PHANTOM_SKINS]

        user = await self.session.get(User, user_id)
        return Inventory(
            held_badges=sorted(held_badges, key=lambda b: b.sort_order),
            unlocked_templates=sorted(unlocked_templates, key=lambda t: t.sort_order),
            unlocked_phantom_skins=sorted(unlocked_skins, key=lambda s: s.sort_order),
            equipped_badge_id=user.equipped_badge_id if user else None,
            equipped_name_template_id=(user.equipped_name_template_id if user else None),
            equipped_phantom_skin_id=(user.equipped_phantom_skin_id if user else None),
        )

    async def get_pending_notifications(self, user_id: uuid.UUID) -> list[RewardNotification]:
        rows = await self.session.execute(
            select(RewardNotification)
            .where(
                RewardNotification.user_id == user_id,
                RewardNotification.dismissed_at.is_(None),
            )
            .order_by(RewardNotification.created_at)
        )
        return list(rows.scalars().all())

    async def dismiss_notifications(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(RewardNotification)
            .where(
                RewardNotification.user_id == user_id,
                RewardNotification.dismissed_at.is_(None),
            )
            .values(dismissed_at=datetime.now(UTC))
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def refresh_top1_elo_holders(self, reason: str | None = None) -> None:
        """Sync the top1_elo badge and grant ELO-rank souvenir templates.

        Filters out provisional players (elo_races < PROVISIONAL_THRESHOLD).

        - top1_elo (transient badge): granted to all users tied at the highest ELO.
          Each holder also receives the elo_crown name template (permanent, idempotent).
        - runebearer (permanent name template): granted to every user currently in the
          top 5 ELO. Ties at the rank-5 boundary pull all tied users in. Once granted,
          the template stays unlocked even if the user later drops out of the top 5.
        """
        max_q = await self.session.execute(
            select(User.elo_rating)
            .where(User.elo_races >= PROVISIONAL_THRESHOLD)
            .order_by(User.elo_rating.desc())
            .limit(1)
        )
        top_elo = max_q.scalar_one_or_none()
        if top_elo is None:
            await self.sync_transient_holders("top1_elo", set(), reason=reason)
            return

        holder_q = await self.session.execute(
            select(User.id).where(
                User.elo_races >= PROVISIONAL_THRESHOLD,
                User.elo_rating == top_elo,
            )
        )
        holders: set[uuid.UUID] = {row[0] for row in holder_q.all()}

        await self.sync_transient_holders("top1_elo", holders, reason=reason)
        for uid in holders:
            await self.grant_name_template(uid, "elo_crown", reason="reached top 1 ELO")
            await self.grant_phantom_skin(uid, "gold-aura", reason="reached top 1 ELO")

        top5_rows = await self.session.execute(
            select(User.elo_rating)
            .where(User.elo_races >= PROVISIONAL_THRESHOLD)
            .order_by(User.elo_rating.desc())
            .limit(5)
        )
        elo_window = list(top5_rows.scalars().all())
        if elo_window:
            fifth_elo = elo_window[-1]
            top5_q = await self.session.execute(
                select(User.id).where(
                    User.elo_races >= PROVISIONAL_THRESHOLD,
                    User.elo_rating >= fifth_elo,
                )
            )
            for uid in {row[0] for row in top5_q.all()}:
                await self.grant_name_template(uid, "runebearer", reason="entered top 5 ELO")
                await self.grant_phantom_skin(uid, "silver-aura", reason="entered top 5 ELO")

    async def refresh_weekly_daily_champion(
        self, week_starting: date, reason: str | None = None
    ) -> None:
        """Sync weekly_daily_champion to the user(s) with the highest total
        points across the week's closed dailies. Selection criterion lives in
        services.daily_points_service.compute_weekly_winners.
        """
        from speedfog_racing.services.daily_points_service import compute_weekly_winners

        winners = await compute_weekly_winners(self.session, week_starting)
        if winners is None:
            # Current or future week; not yet decided. Defensive no-op.
            return
        holders = {w.user.id for w in winners}
        await self.sync_transient_holders("weekly_daily_champion", holders, reason=reason)
        for uid in holders:
            await self.grant_phantom_skin(uid, "cyan-aura", reason="weekly daily champion")

    async def check_finish_reward_milestones(self, user_id: uuid.UUID) -> None:
        """Grant finished-race milestone rewards.

        - Frog badge + Speedfrog template at the first finished race.
        - Veteran badge + weathered template + crimson-aura at VETERAN_RACE_THRESHOLD.

        Idempotent: grant_permanent_badge and grant_name_template both no-op on
        re-grant. Safe to call after every race finish; counts only Participant
        rows with status=FINISHED across all races (daily seeds included, solo
        training sessions excluded since they create no Participant row).
        """
        count = await self.session.scalar(
            select(func.count(Participant.id)).where(
                Participant.user_id == user_id,
                Participant.status == ParticipantStatus.FINISHED,
            )
        )
        finished = count or 0
        if finished >= 1:
            reason = f"finished {finished} race(s)"
            await self.grant_permanent_badge(user_id, "frog", reason=reason)
            await self.grant_name_template(user_id, "speedfrog", reason=reason)
        if finished >= VETERAN_RACE_THRESHOLD:
            reason = f"finished {finished} races"
            await self.grant_permanent_badge(user_id, "veteran", reason=reason)
            await self.grant_name_template(user_id, "weathered", reason=reason)
            await self.grant_phantom_skin(user_id, "crimson-aura", reason=reason)

    async def check_daily_streak_eligibility(self, user_id: uuid.UUID) -> None:
        """Grant molten-aura when the user's best daily streak reaches the threshold.

        Reads ``users.daily_best_streak`` (the all-time high water mark) and grants
        the permanent ``molten-aura`` phantom skin once it is at least
        ``DAILY_STREAK_REWARD_THRESHOLD``. Using the best-streak field (rather than
        the current streak) means the unlock survives a later streak break and lets
        the backfill use the same predicate without a separate code path.

        Idempotent: ``grant_phantom_skin`` no-ops on re-grant, so callers can fire
        this on every qualification.
        """
        best = await self.session.scalar(select(User.daily_best_streak).where(User.id == user_id))
        if (best or 0) >= DAILY_STREAK_REWARD_THRESHOLD:
            await self.grant_phantom_skin(
                user_id,
                "molten-aura",
                reason=f"reached {best}-day daily streak",
            )

    async def revoke_badge(self, user_id: uuid.UUID, badge_id: str) -> None:
        if badge_id not in BADGES:
            raise UnknownRewardError(f"Unknown badge_id={badge_id!r}")
        await self.session.execute(
            update(BadgeGrant)
            .where(
                BadgeGrant.user_id == user_id,
                BadgeGrant.badge_id == badge_id,
                BadgeGrant.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.execute(
            update(User)
            .where(User.id == user_id, User.equipped_badge_id == badge_id)
            .values(equipped_badge_id=None)
        )

    async def revoke_name_template(self, user_id: uuid.UUID, template_id: str) -> None:
        if template_id not in NAME_TEMPLATES:
            raise UnknownRewardError(f"Unknown template_id={template_id!r}")
        if template_id == DEFAULT_TEMPLATE_ID:
            return
        await self.session.execute(
            delete(NameTemplateUnlock).where(
                NameTemplateUnlock.user_id == user_id,
                NameTemplateUnlock.template_id == template_id,
            )
        )
        await self.session.execute(
            update(User)
            .where(
                User.id == user_id,
                User.equipped_name_template_id == template_id,
            )
            .values(equipped_name_template_id=None)
        )

    async def revoke_phantom_skin(self, user_id: uuid.UUID, skin_id: str) -> None:
        if skin_id not in PHANTOM_SKINS:
            raise UnknownRewardError(f"Unknown skin_id={skin_id!r}")
        if skin_id == DEFAULT_PHANTOM_SKIN_ID:
            return
        await self.session.execute(
            delete(PhantomSkinUnlock).where(
                PhantomSkinUnlock.user_id == user_id,
                PhantomSkinUnlock.skin_id == skin_id,
            )
        )
        await self.session.execute(
            update(User)
            .where(
                User.id == user_id,
                User.equipped_phantom_skin_id == skin_id,
            )
            .values(equipped_phantom_skin_id=None)
        )
