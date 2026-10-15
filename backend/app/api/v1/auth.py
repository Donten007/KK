"""认证路由（只挂端点 + 接依赖，不写逻辑）。

限流：登录/注册/刷新按 IP + 端点 10 次/分钟（SPEC §4.5 安全清单）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AuthUser, PlainSession
from app.controllers import auth as controller
from app.middlewares.rate_limit import RateLimitPolicy, rate_limit
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_SENSITIVE = RateLimitPolicy(limit=10, window_seconds=60)


@router.post("/register", status_code=201, dependencies=[Depends(rate_limit(_SENSITIVE))])
async def register(body: RegisterRequest, session: PlainSession) -> ApiResponse:
    return await controller.register(body, session)


@router.post("/login", dependencies=[Depends(rate_limit(_SENSITIVE))])
async def login(body: LoginRequest, session: PlainSession) -> ApiResponse:
    return await controller.login(body, session)


@router.post("/refresh", dependencies=[Depends(rate_limit(_SENSITIVE))])
async def refresh(body: RefreshRequest, session: PlainSession) -> ApiResponse:
    return await controller.refresh(body, session)


@router.post("/logout")
async def logout(body: LogoutRequest, session: PlainSession) -> ApiResponse:
    return await controller.logout(body, session)


@router.get("/me")
async def me(user: AuthUser, session: PlainSession) -> ApiResponse:
    return await controller.me(user, session)
