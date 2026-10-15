"""账套控制器：创建 / 详情 / 更新 / 成员管理 / 切换。不含业务逻辑。"""

from __future__ import annotations

import uuid

from app.api.deps import AuthUser, PlainSession, TenantSession
from app.schemas.common import ApiResponse, ok
from app.services.tenant_service import TenantService
from pydantic import BaseModel, EmailStr, Field


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


class SwitchTenantRequest(BaseModel):
    tenant_id: uuid.UUID


async def create_tenant(body: CreateTenantRequest, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    tenant = await service.create_tenant(user_id=user.user_id, name=body.name)
    return ok(tenant.model_dump(mode="json"))


async def get_current(user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    tenant = await service.get_current(tenant_id=user.tenant_id)
    return ok(tenant.model_dump(mode="json"))


async def update_current(body: UpdateTenantRequest, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    tenant = await service.update_current(tenant_id=user.tenant_id, name=body.name)
    return ok(tenant.model_dump(mode="json"))


async def list_members(user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    members = await service.list_members(tenant_id=user.tenant_id)
    return ok(members)


async def invite_member(body: InviteMemberRequest, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    member = await service.invite_member(
        tenant_id=user.tenant_id, actor_id=user.user_id, email=body.email, role=body.role
    )
    return ok(member)


async def update_member_role(
    target_user_id: uuid.UUID, body: UpdateRoleRequest, user: AuthUser, session: TenantSession
) -> ApiResponse:
    service = TenantService(session)
    member = await service.update_member_role(
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        target_user_id=target_user_id,
        role=body.role,
    )
    return ok(member)


async def remove_member(target_user_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = TenantService(session)
    await service.remove_member(
        tenant_id=user.tenant_id, actor_id=user.user_id, target_user_id=target_user_id
    )
    return ok()


async def switch_tenant(body: SwitchTenantRequest, user: AuthUser, session: PlainSession) -> ApiResponse:
    # 注意：本端点必须用 PlainSession——它要跨到目标账套的 RLS 上下文，
    # 若用 TenantSession（已绑定旧账套 GUC），嵌套 set_config 会在 savepoint
    # 释放后污染外层事务的租户上下文。
    service = TenantService(session)
    tenant, tokens = await service.switch_tenant(
        user_id=user.user_id, tenant_id=body.tenant_id
    )
    return ok({"tenant": tenant.model_dump(mode="json"), "tokens": tokens.model_dump(mode="json")})
