"""Rewards HTTP endpoints (public catalog + authenticated player APIs)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import User
from speedfog_racing.rewards.catalog import BADGES, NAME_TEMPLATES
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
                "background_css": t.background_css,
                "sort_order": t.sort_order,
            }
            for t in sorted(NAME_TEMPLATES.values(), key=lambda t: t.sort_order)
        ],
    }


class EquipPayload(BaseModel):
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None


@router.get("/me")
async def get_my_inventory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:  # type: ignore[type-arg]
    svc = RewardsService(db)
    inv = await svc.get_user_inventory(user.id)
    return {
        "held_badges": [
            {"id": b.id, "name": b.name, "icon_filename": b.icon_filename} for b in inv.held_badges
        ],
        "unlocked_templates": [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "gradient": list(t.gradient) if t.gradient else None,
                "background_css": t.background_css,
            }
            for t in inv.unlocked_templates
        ],
        "equipped_badge_id": inv.equipped_badge_id,
        "equipped_name_template_id": inv.equipped_name_template_id,
    }


@router.patch("/me/equipped")
async def patch_equipped(
    payload: EquipPayload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:  # type: ignore[type-arg]
    svc = RewardsService(db)
    body = payload.model_dump(exclude_unset=True)
    try:
        if "equipped_badge_id" in body:
            await svc.set_equipped_badge(user.id, body["equipped_badge_id"])
        if "equipped_name_template_id" in body:
            await svc.set_equipped_name_template(user.id, body["equipped_name_template_id"])
    except (NotOwnedError, UnknownRewardError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    inv = await svc.get_user_inventory(user.id)
    return {
        "equipped_badge_id": inv.equipped_badge_id,
        "equipped_name_template_id": inv.equipped_name_template_id,
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
