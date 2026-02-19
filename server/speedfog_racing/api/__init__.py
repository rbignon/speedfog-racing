"""API routes aggregation."""

from fastapi import APIRouter

from speedfog_racing.api.admin import router as admin_router
from speedfog_racing.api.auth import router as auth_router
from speedfog_racing.api.i18n import router as i18n_router
from speedfog_racing.api.invites import router as invites_router
from speedfog_racing.api.pools import router as pools_router
from speedfog_racing.api.races import router as races_router
from speedfog_racing.api.training import router as training_router
from speedfog_racing.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(i18n_router, prefix="/i18n", tags=["i18n"])
api_router.include_router(races_router, prefix="/races", tags=["races"])
api_router.include_router(pools_router, prefix="/pools", tags=["pools"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(invites_router, prefix="/invite", tags=["invites"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_router.include_router(training_router, prefix="/training", tags=["training"])
