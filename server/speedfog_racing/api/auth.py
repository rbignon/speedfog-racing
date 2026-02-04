"""Authentication API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/twitch")
async def twitch_login() -> dict:
    """Redirect to Twitch OAuth.

    TODO: Implement in Step 2.
    """
    return {"message": "TODO: Redirect to Twitch OAuth"}


@router.get("/callback")
async def twitch_callback(code: str | None = None, state: str | None = None) -> dict:
    """Handle Twitch OAuth callback.

    TODO: Implement in Step 2.
    """
    return {"message": "TODO: Handle callback", "code": code, "state": state}


@router.get("/me")
async def get_current_user() -> dict:
    """Get current authenticated user.

    TODO: Implement in Step 2.
    """
    return {"message": "TODO: Return current user"}
