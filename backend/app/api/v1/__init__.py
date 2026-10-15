"""v1 路由聚合。新资源路由在此登记，入口只 include 本聚合器。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import analytics, auth, goals, health, reports, tenants

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(goals.router)
api_router.include_router(reports.router)
api_router.include_router(reports.usage_router)
api_router.include_router(analytics.router)
