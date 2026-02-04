"""User API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/me")
async def get_me() -> dict:
    """Get current user profile.

    TODO: Implement in Step 2.
    """
    return {"message": "TODO: Get current user"}
