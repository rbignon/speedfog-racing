"""Public catalogue endpoint for the equipped-weapons frontend resolution.

Serves the static ``services.weapons.WEAPONS`` mapping. Authentication is
optional today; future locale-aware variants will switch on ``User.locale``
without breaking anonymous callers.
"""

from dataclasses import asdict

from fastapi import APIRouter, Response

from speedfog_racing.services.weapons import WEAPONS

router = APIRouter()

_CACHE_CONTROL = "public, max-age=3600"
_BODY: dict[str, dict[str, int | str]] = {
    str(weapon_id): asdict(info) for weapon_id, info in WEAPONS.items()
}


@router.get("")
async def get_weapons_catalogue(response: Response) -> dict[str, dict[str, int | str]]:
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return _BODY
