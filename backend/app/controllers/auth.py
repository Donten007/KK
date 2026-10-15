"""认证控制器：参数 → 调 service → 组装信封响应。不含业务逻辑。"""

from __future__ import annotations

from app.api.deps import AuthUser, PlainSession
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest
from app.schemas.common import ApiResponse, ok
from app.services.auth_service import AuthService
from app.services.user_service import UserService


async def register(body: RegisterRequest, session: PlainSession) -> ApiResponse:
    service = AuthService(session)
    result = await service.register(
        email=body.email, password=body.password, company_name=body.company_name
    )
    return ok(result.model_dump(mode="json"))


async def login(body: LoginRequest, session: PlainSession) -> ApiResponse:
    service = AuthService(session)
    result = await service.login(email=body.email, password=body.password)
    return ok(result.model_dump(mode="json"))


async def refresh(body: RefreshRequest, session: PlainSession) -> ApiResponse:
    service = AuthService(session)
    result = await service.refresh(refresh_token=body.refresh_token)
    return ok(result.model_dump(mode="json"))


async def logout(body: LogoutRequest, session: PlainSession) -> ApiResponse:
    service = AuthService(session)
    await service.logout(refresh_token=body.refresh_token)
    return ok()


async def me(user: AuthUser, session: PlainSession) -> ApiResponse:
    service = UserService(session)
    profile = await service.get_profile(user.user_id)
    return ok(profile.model_dump(mode="json"))
