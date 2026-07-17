from fastapi import APIRouter

from app.api.v1.endpoints import health, workflow

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(workflow.router, tags=["workflow"])
