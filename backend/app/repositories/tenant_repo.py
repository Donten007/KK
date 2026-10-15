"""tenants / tenant_members 仓库。

tenants 无 RLS（账套注册表）；tenant_members 有 RLS，方法带 tenant_id 且
逐个触发 ensure_tenant_context 校验（查询层防护，ADR-003 三层之一）。
"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError
from app.models.tenant import Tenant, TenantMember
from app.repositories.base import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class TenantRepository:
    """账套仓库（无 RLS）。code 唯一即注册表，按 code/id 精确查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Tenant | None:
        result = await self.session.execute(select(Tenant).where(Tenant.code == code))
        return result.scalar_one_or_none()

    async def code_exists(self, code: str) -> bool:
        result = await self.session.execute(select(Tenant.id).where(Tenant.code == code))
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        *,
        code: str,
        name: str,
        plan: str = "trial",
        tenant_dek: str | None = None,
        human_hourly_rate_cents: int = 0,
    ) -> Tenant:
        tenant = Tenant(
            code=code,
            name=name,
            plan=plan,
            tenant_dek=tenant_dek,
            human_hourly_rate_cents=human_hourly_rate_cents,
        )
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    async def update_name(self, tenant_id: uuid.UUID, name: str) -> None:
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            return
        tenant.name = name
        await self.session.flush()


class TenantMemberRepository(BaseRepository):
    """成员仓库（RLS 保护）。所有方法带 tenant_id 并触发上下文校验。"""

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[TenantMember]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TenantMember).where(TenantMember.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def get_membership(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> TenantMember | None:
        """可选查询。跨租户与不存在都返回 None（RLS 已过滤，服务层无从区分）。"""
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def require_membership(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> TenantMember:
        """必需查询。跨租户与不存在抛**同一个** NotFoundError（坑 5：
        403 是资源枚举 oracle，服务层不可区分两种情况）。"""
        member = await self.get_membership(tenant_id=tenant_id, user_id=user_id)
        if member is None:
            raise NotFoundError()
        return member

    async def add_member(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str
    ) -> TenantMember:
        """新增成员。调用方会话必须已设置租户上下文（RLS WITH CHECK 要求）。
        注意：登录解析不经过本方法（无上下文时 RLS fail-closed），
        用户-账套关联索引走 UserTenantLinkRepository（无 RLS）。"""
        await self._guard(tenant_id)
        member = TenantMember(tenant_id=tenant_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member

    async def update_role(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is not None:
            member.role = role
            await self.session.flush()

    async def remove_member(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is not None:
            await self.session.delete(member)
            await self.session.flush()
