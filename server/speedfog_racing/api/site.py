"""Public site configuration endpoint."""

from fastapi import APIRouter

from speedfog_racing.config import settings

router = APIRouter()


@router.get("/site-config")
async def site_config() -> dict[str, bool]:
    """Public site configuration."""
    return {"coming_soon": settings.coming_soon}
