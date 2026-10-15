"""账套服务：创建 / 当前账套 / 更新 / 成员管理 / 切换账套。

角色权限（SPEC §5.2 端点索引）：
- 创建账套：任意已认证用户
- 更新/删除账套、邀请/改角色/移除成员：owner / admin
- 查看：成员及以上

切换账套：更新 users.last_tenant_id 并签发新账套作用域的 token；
RLS 的 SET LOCAL 随之切换（新 token 的 tenant_id 即新上下文）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.core.crypto import generate_dek, wrap_dek
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    refresh_expires_at,
)
from app.db.rls import tenant_scope, tenant_transaction, work_unit
from app.repositories.audit_repo import AuditLogRepository
from app.repositories.tenant_link_repo import UserTenantLinkRepository
from app.repositories.tenant_repo import TenantMemberRepository, TenantRepository
from app.repositories.user_repo import RefreshTokenRepository, UserRepository
from app.schemas.auth import TenantOut, TokenPairOut
from app.utils.ids import generate_tenant_code
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tenant")

ROLE_RANK = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}
VALID_ROLES = frozenset(ROLE_RANK)


class TenantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tenants = TenantRepository(session)
        self.members = TenantMemberRepository(session)
        self.links = UserTenantLinkRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.audit = AuditLogRepository(session)

    async def create_tenant(self, *, user_id: uuid.UUID, name: str) -> TenantOut:
        """已认证用户创建新账套（创建者成为 owner）。"""
        if not name or not name.strip():
            raise ValidationError("账套名称不能为空")
        code = await self._fresh_code()

        async with work_unit(self.session):
            tenant = await self.tenants.create(
                code=code, name=name.strip()[:200], tenant_dek=wrap_dek(generate_dek())
            )
            async with tenant_scope(self.session, tenant.id):
                await self.members.add_member(tenant_id=tenant.id, user_id=user_id, role="owner")
                await self.links.add(user_id=user_id, tenant_id=tenant.id, role="owner")
                await self.audit.record(
                    tenant_id=tenant.id,
                    event_type="tenant_created",
                    actor_id=user_id,
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                )

        return TenantOut.model_validate(tenant)

    async def get_current(self, *, tenant_id: uuid.UUID) -> TenantOut:
        async with tenant_transaction(self.session, tenant_id):
            tenant = await self.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError()
        return TenantOut.model_validate(tenant)

    async def update_current(self, *, tenant_id: uuid.UUID, name: str) -> TenantOut:
        if not name or not name.strip():
            raise ValidationError("账套名称不能为空")
        async with tenant_transaction(self.session, tenant_id):
            await self.tenants.update_name(tenant_id, name.strip()[:200])
            tenant = await self.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError()
        return TenantOut.model_validate(tenant)

    async def list_members(
        self, *, tenant_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with tenant_transaction(self.session, tenant_id):
            members = await self.members.list_for_tenant(tenant_id)
            users = await self.users.get_by_ids([m.user_id for m in members])
        result = []
        for m in members:
            user = users.get(m.user_id)
            result.append(
                {
                    "user_id": str(m.user_id),
                    "email": user.email if user else None,
                    "role": m.role,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
        return result

    async def invite_member(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, email: str, role: str
    ) -> dict[str, Any]:
        if role not in VALID_ROLES or role == "owner":
            raise ValidationError("角色必须是 admin / member / viewer 之一")
        async with tenant_transaction(self.session, tenant_id):
            user = await self.users.get_by_email(email)
            if user is None:
                raise NotFoundError("用户不存在，请先注册")
            existing = await self.members.get_membership(tenant_id=tenant_id, user_id=user.id)
            if existing is not None:
                raise ConflictError("该用户已是本账套成员")
            await self.members.add_member(tenant_id=tenant_id, user_id=user.id, role=role)
            await self.links.add(user_id=user.id, tenant_id=tenant_id, role=role)
            await self.audit.record(
                tenant_id=tenant_id,
                event_type="member_invited",
                actor_id=actor_id,
                resource_type="user",
                resource_id=str(user.id),
            )
        return {"user_id": str(user.id), "email": user.email, "role": role}

    async def update_member_role(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, target_user_id: uuid.UUID, role: str
    ) -> dict[str, Any]:
        if role not in VALID_ROLES:
            raise ValidationError("角色不合法")
        if target_user_id == actor_id and role != "owner":
            raise ValidationError("不能降级自己的角色，请由其他 owner 操作")
        async with tenant_transaction(self.session, tenant_id):
            target = await self.members.get_membership(
                tenant_id=tenant_id, user_id=target_user_id
            )
            if target is None:
                raise NotFoundError()
            if target.role == "owner" and role != "owner":
                raise ForbiddenError("不能修改 owner 的角色")
            await self.members.update_role(
                tenant_id=tenant_id, user_id=target_user_id, role=role
            )
            await self.links.update_role(user_id=target_user_id, tenant_id=tenant_id, role=role)
            await self.audit.record(
                tenant_id=tenant_id,
                event_type="member_role_changed",
                actor_id=actor_id,
                resource_type="user",
                resource_id=str(target_user_id),
            )
        return {"user_id": str(target_user_id), "role": role}

    async def remove_member(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, target_user_id: uuid.UUID
    ) -> None:
        if target_user_id == actor_id:
            raise ValidationError("不能移除自己")
        async with tenant_transaction(self.session, tenant_id):
            target = await self.members.get_membership(
                tenant_id=tenant_id, user_id=target_user_id
            )
            if target is None:
                raise NotFoundError()
            if target.role == "owner":
                raise ForbiddenError("不能移除 owner")
            await self.members.remove_member(tenant_id=tenant_id, user_id=target_user_id)
            await self.links.remove(user_id=target_user_id, tenant_id=tenant_id)
            await self.audit.record(
                tenant_id=tenant_id,
                event_type="member_removed",
                actor_id=actor_id,
                resource_type="user",
                resource_id=str(target_user_id),
            )

    async def switch_tenant(self, *, user_id: uuid.UUID, tenant_id: uuid.UUID) -> tuple[TenantOut, TokenPairOut]:
        """切换当前账套：校验成员关系 → 更新 last_tenant_id → 签发新作用域 token。"""
        link = await self.links.get(user_id=user_id, tenant_id=tenant_id)
        if link is None:
            # 非成员：与「账套不存在」不可区分（404 语义）
            raise NotFoundError("账套不存在或你已失去访问权限")
        now = datetime.now(UTC)
        async with tenant_transaction(self.session, tenant_id):
            await self.users.set_last_tenant(user_id, tenant_id)
            # token_id 必须等于行主键（refresh 定位旧行靠 jti），与 AuthService 同一约定
            token_id = uuid.uuid4()
            token = create_refresh_token(
                user_id=user_id, tenant_id=tenant_id, token_id=token_id
            )
            await self.refresh_tokens.create(
                tenant_id=tenant_id,
                user_id=user_id,
                token_hash=hash_refresh_token(token),
                expires_at=now + timedelta(days=7),
                row_id=token_id,
            )
            tenant = await self.tenants.get_by_id(tenant_id)
            await self.audit.record(
                tenant_id=tenant_id,
                event_type="tenant_switched",
                actor_id=user_id,
                resource_type="tenant",
                resource_id=str(tenant_id),
            )
        if tenant is None:
            raise NotFoundError()
        access = create_access_token(user_id=user_id, tenant_id=tenant_id, role=link.role)
        tokens = TokenPairOut(
            access_token=access,
            refresh_token=token,
            expires_in=get_settings().jwt_access_ttl_seconds,
            refresh_expires_at=refresh_expires_at(token),
        )
        return TenantOut.model_validate(tenant), tokens

    async def _fresh_code(self) -> str:
        for _ in range(5):
            code = generate_tenant_code()
            if not await self.tenants.code_exists(code):
                return code
        raise ConflictError("账套号生成冲突，请重试")
