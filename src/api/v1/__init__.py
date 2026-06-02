from fastapi import APIRouter

from src.api.v1.assets import router as assets_router
from src.api.v1.auth import router as auth_router
from src.api.v1.users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(assets_router, prefix="/assets", tags=["Assets"])
