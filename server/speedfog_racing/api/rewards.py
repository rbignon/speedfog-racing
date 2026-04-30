"""Rewards HTTP endpoints (public catalog + authenticated player APIs)."""

from fastapi import APIRouter

from speedfog_racing.rewards.catalog import BADGES, NAME_TEMPLATES

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
