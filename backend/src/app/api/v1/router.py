from fastapi import APIRouter

from app.api.v1.endpoints import auth, campaigns, donors, health, workflow

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(donors.router, tags=["donors"])
api_router.include_router(campaigns.router, tags=["campaigns"])
api_router.include_router(workflow.router, tags=["workflow"])
