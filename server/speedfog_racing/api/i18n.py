"""i18n API routes."""

from fastapi import APIRouter

from speedfog_racing.services.i18n import get_available_locales

router = APIRouter()


@router.get("/locales")
async def list_locales() -> list[dict[str, str]]:
    """Return available locales (public, no auth required)."""
    return get_available_locales()
