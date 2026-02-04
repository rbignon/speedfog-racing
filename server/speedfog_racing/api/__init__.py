"""API routes aggregation."""

from fastapi import APIRouter

from speedfog_racing.api.auth import router as auth_router
from speedfog_racing.api.races import router as races_router
from speedfog_racing.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(races_router, prefix="/races", tags=["races"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
