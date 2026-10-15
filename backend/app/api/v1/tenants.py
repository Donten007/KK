"""账套路由（只挂端点 + 接依赖，不写逻辑）。

角色守卫（SPEC §5.2）：
- POST /tenants：任意已认证用户
- GET /tenants/current、members：成员及以上
- PATCH/DELETE /tenants/current、邀请/改角色/移除成员：admin 及以上
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import AuthUser, PlainSession, TenantSession, require_role
from app.controllers import tenant as controller
from app.controllers.tenant import (
    CreateTenantRequest,
    InviteMemberRequest,
    SwitchTenantRequest,
    UpdateRoleRequest,
    UpdateTenantRequest,
)
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("", status_code=201)
async def create_tenant(body: CreateTenantRequest, user: AuthUser, session: TenantSession) -> ApiResponse:
    return await controller.create_tenant(body, user, session)


@router.get("/current")
async def get_current(user: AuthUser, session: TenantSession) -> ApiResponse:
    return await controller.get_current(user, session)


@router.patch("/current", dependencies=[Depends(require_role("admin"))])
async def update_current(
    body: UpdateTenantRequest, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.update_current(body, user, session)


@router.post("/current/switch")
async def switch_tenant(body: SwitchTenantRequest, user: AuthUser, session: PlainSession) -> ApiResponse:
    return await controller.switch_tenant(body, user, session)


@router.get("/current/members")
async def list_members(user: AuthUser, session: TenantSession) -> ApiResponse:
    return await controller.list_members(user, session)


@router.post("/current/members", status_code=201, dependencies=[Depends(require_role("admin"))])
async def invite_member(
    body: InviteMemberRequest, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.invite_member(body, user, session)


@router.patch(
    "/current/members/{target_user_id}", dependencies=[Depends(require_role("admin"))]
)
async def update_member_role(
    target_user_id: uuid.UUID,
    body: UpdateRoleRequest,
    user: AuthUser,
    session: TenantSession,
) -> ApiResponse:
    return await controller.update_member_role(target_user_id, body, user, session)


@router.delete("/current/members/{target_user_id}", dependencies=[Depends(require_role("admin"))])
async def remove_member(
    target_user_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.remove_member(target_user_id, user, session)
