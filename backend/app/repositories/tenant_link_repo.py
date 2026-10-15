"""user_tenant_links 仓库（无 RLS）：登录时的账套解析。

role 优先级：owner > admin > member > viewer。多账套用户登录时取最高权重的
账套（与 users.last_tenant_id 配合：last_tenant_id 命中且仍是成员则优先）。
"""

from __future__ import annotations

import uuid

from app.models.tenant_link import UserTenantLink
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_ROLE_WEIGHT = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}


class UserTenantLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserTenantLink]:
        result = await self.session.execute(
            select(UserTenantLink).where(UserTenantLink.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get(
        self, *, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> UserTenantLink | None:
        result = await self.session.execute(
            select(UserTenantLink).where(
                UserTenantLink.user_id == user_id,
                UserTenantLink.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def resolve_login_tenant(
        self, *, user_id: uuid.UUID, last_tenant_id: uuid.UUID | None
    ) -> tuple[uuid.UUID, str] | None:
        """登录账套解析：last_tenant_id 优先，否则取角色权重最高的账套。"""
        links = await self.list_for_user(user_id)
        if not links:
            return None
        if last_tenant_id is not None:
            for link in links:
                if link.tenant_id == last_tenant_id:
                    return link.tenant_id, link.role
        best = max(links, key=lambda item: _ROLE_WEIGHT.get(item.role, 0))
        return best.tenant_id, best.role

    async def add(self, *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> UserTenantLink:
        link = UserTenantLink(user_id=user_id, tenant_id=tenant_id, role=role)
        self.session.add(link)
        await self.session.flush()
        return link

    async def update_role(self, *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> None:
        result = await self.session.execute(
            select(UserTenantLink).where(
                UserTenantLink.user_id == user_id,
                UserTenantLink.tenant_id == tenant_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is not None:
            link.role = role
            await self.session.flush()

    async def remove(self, *, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(UserTenantLink).where(
                UserTenantLink.user_id == user_id,
                UserTenantLink.tenant_id == tenant_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is not None:
            await self.session.delete(link)
            await self.session.flush()
