"""Rewards service: grant, revoke, sync, equip, read."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    Participant,
    ParticipantStatus,
    Race,
    RewardNotification,
    User,
)
from speedfog_racing.rewards.catalog import (
    BADGES,
    DEFAULT_TEMPLATE_ID,
    NAME_TEMPLATES,
    VETERAN_RACE_THRESHOLD,
)
from speedfog_racing.rewards.models_data import Badge, NameTemplate
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
    equipped_badge_id: str | None
    equipped_name_template_id: str | None


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

        user = await self.session.get(User, user_id)
        return Inventory(
            held_badges=sorted(held_badges, key=lambda b: b.sort_order),
            unlocked_templates=sorted(unlocked_templates, key=lambda t: t.sort_order),
            equipped_badge_id=user.equipped_badge_id if user else None,
            equipped_name_template_id=(user.equipped_name_template_id if user else None),
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

    async def refresh_weekly_daily_champion(
        self, week_starting: date, reason: str | None = None
    ) -> None:
        """Sync weekly_daily_champion to the user(s) who won the most daily seeds in
        the [week_starting, week_starting + 7d) range.

        A "win" is a Participant in a daily race (Race.daily_date IN that range)
        with status FINISHED and the lowest igt_ms among finishers (one winner per day).
        """
        week_end = week_starting + timedelta(days=7)

        finishers = (
            select(
                Participant.race_id.label("race_id"),
                func.min(Participant.igt_ms).label("min_igt"),
            )
            .join(Race, Race.id == Participant.race_id)
            .where(
                Race.daily_date >= week_starting,
                Race.daily_date < week_end,
                Participant.status == ParticipantStatus.FINISHED,
            )
            .group_by(Participant.race_id)
            .subquery()
        )

        winners = (
            select(Participant.user_id, func.count().label("wins"))
            .join(
                finishers,
                (Participant.race_id == finishers.c.race_id)
                & (Participant.igt_ms == finishers.c.min_igt),
            )
            .where(Participant.status == ParticipantStatus.FINISHED)
            .group_by(Participant.user_id)
        )
        rows = (await self.session.execute(winners)).all()
        if not rows:
            await self.sync_transient_holders("weekly_daily_champion", set(), reason=reason)
            return

        max_wins = max(r.wins for r in rows)
        holders = {r.user_id for r in rows if r.wins == max_wins}
        await self.sync_transient_holders("weekly_daily_champion", holders, reason=reason)

    async def check_veteran_eligibility(self, user_id: uuid.UUID) -> None:
        """Grant the veteran badge and weathered template at VETERAN_RACE_THRESHOLD finishes.

        Idempotent: grant_permanent_badge and grant_name_template both no-op on
        re-grant. Safe to call after every race finish; counts only Participant
        rows with status=FINISHED across all races.
        """
        count = await self.session.scalar(
            select(func.count(Participant.id)).where(
                Participant.user_id == user_id,
                Participant.status == ParticipantStatus.FINISHED,
            )
        )
        if (count or 0) >= VETERAN_RACE_THRESHOLD:
            reason = f"finished {count} races"
            await self.grant_permanent_badge(user_id, "veteran", reason=reason)
            await self.grant_name_template(user_id, "weathered", reason=reason)

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
