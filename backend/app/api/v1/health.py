"""健康检查路由（SPEC §12.1 断言 /health 返回服务健康）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> ApiResponse:
    return ok({"status": "ok"})


@router.get("/health/ready")
async def readiness() -> ApiResponse:
    """就绪探针：只报告进程状态。数据库深度检查由部署编排层负责
    （避免 /health 被探测流量打爆数据库）。"""
    return ok({"status": "ready"})
