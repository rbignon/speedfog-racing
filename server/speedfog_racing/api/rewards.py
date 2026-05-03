"""Rewards HTTP endpoints (public catalog + authenticated player APIs)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import User, UserRole
from speedfog_racing.rewards.catalog import BADGES, NAME_TEMPLATES, PHANTOM_SKINS
from speedfog_racing.rewards.service import NotOwnedError, RewardsService, UnknownRewardError

router = APIRouter()


@router.get("/catalog")
async def get_catalog() -> dict:  # type: ignore[type-arg]
    return {
        "badges": [
            {
                "id": b.id,
                "name": b.name,
                "description": b.description,
                "icon_filename": b.icon_filename,
                "lifecycle": b.lifecycle,
                "sort_order": b.sort_order,
            }
            for b in sorted(BADGES.values(), key=lambda b: b.sort_order)
        ],
        "name_templates": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "color": t.color,
                "gradient": list(t.gradient) if t.gradient is not None else None,
                "name_css": t.name_css,
                "background_css": t.background_css,
                "sort_order": t.sort_order,
            }
            for t in sorted(NAME_TEMPLATES.values(), key=lambda t: t.sort_order)
        ],
        "phantom_skins": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "screenshot_filename": s.screenshot_filename,
                "sort_order": s.sort_order,
                "obtainable": s.obtainable,
            }
            for s in sorted(PHANTOM_SKINS.values(), key=lambda s: s.sort_order)
        ],
    }


class EquipPayload(BaseModel):
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None
    equipped_phantom_skin_id: str | None = None


@router.get("/me")
async def get_my_inventory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:  # type: ignore[type-arg]
    svc = RewardsService(db)
    inv = await svc.get_user_inventory(user.id)
    # Admin debug override: surface the full catalog so admins can preview any
    # badge/template without holding it. Not a real ownership claim. The
    # equipped_* fields below remain the truthful DB state, so an admin who
    # PATCHes a force-equip will see that exact value back here AND on every
    # public surface (chat, leaderboard, spectator, profile). That is intended:
    # the debug knob exists to test how rewards render in the real frontends.
    if user.role == UserRole.ADMIN:
        held_badges = sorted(BADGES.values(), key=lambda b: b.sort_order)
        unlocked_templates = sorted(NAME_TEMPLATES.values(), key=lambda t: t.sort_order)
        unlocked_phantom_skins = sorted(PHANTOM_SKINS.values(), key=lambda s: s.sort_order)
    else:
        held_badges = inv.held_badges
        unlocked_templates = inv.unlocked_templates
        unlocked_phantom_skins = inv.unlocked_phantom_skins
    return {
        "held_badges": [
            {"id": b.id, "name": b.name, "icon_filename": b.icon_filename} for b in held_badges
        ],
        "unlocked_templates": [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "gradient": list(t.gradient) if t.gradient else None,
                "name_css": t.name_css,
                "background_css": t.background_css,
            }
            for t in unlocked_templates
        ],
        "unlocked_phantom_skins": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "screenshot_filename": s.screenshot_filename,
                "sort_order": s.sort_order,
                "obtainable": s.obtainable,
            }
            for s in unlocked_phantom_skins
        ],
        "equipped_badge_id": inv.equipped_badge_id,
        "equipped_name_template_id": inv.equipped_name_template_id,
        "equipped_phantom_skin_id": inv.equipped_phantom_skin_id,
    }


@router.patch("/me/equipped")
async def patch_equipped(
    payload: EquipPayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:  # type: ignore[type-arg]
    svc = RewardsService(db)
    body = payload.model_dump(exclude_unset=True)
    enforce_ownership = user.role != UserRole.ADMIN
    try:
        if "equipped_badge_id" in body:
            await svc.set_equipped_badge(
                user.id, body["equipped_badge_id"], enforce_ownership=enforce_ownership
            )
        if "equipped_name_template_id" in body:
            await svc.set_equipped_name_template(
                user.id,
                body["equipped_name_template_id"],
                enforce_ownership=enforce_ownership,
            )
        if "equipped_phantom_skin_id" in body:
            await svc.set_equipped_phantom_skin(
                user.id,
                body["equipped_phantom_skin_id"],
                enforce_ownership=enforce_ownership,
            )
    except (NotOwnedError, UnknownRewardError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    inv = await svc.get_user_inventory(user.id)
    return {
        "equipped_badge_id": inv.equipped_badge_id,
        "equipped_name_template_id": inv.equipped_name_template_id,
        "equipped_phantom_skin_id": inv.equipped_phantom_skin_id,
    }


@router.get("/notifications")
async def get_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:  # type: ignore[type-arg]
    svc = RewardsService(db)
    rows = await svc.get_pending_notifications(user.id)
    return [
        {
            "id": str(n.id),
            "kind": n.kind,
            "reward_id": n.reward_id,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]


@router.post("/notifications/dismiss", status_code=204)
async def dismiss_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    svc = RewardsService(db)
    await svc.dismiss_notifications(user.id)
    await db.commit()
    return Response(status_code=204)
