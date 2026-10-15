"""阻断级：仓库层查询防护与一致性（SPEC §9.7 用例 12-14 / 坑 4 / 坑 5）。

查询层防护是 ADR-003 三层之一：Repository 签名强制 tenant_id（编译期）+
会话上下文校验（运行期）+ 跨租户与不存在不可区分（坑 5）。
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import NotFoundError
from app.db.rls import tenant_transaction
from app.models.tenant import Tenant
from app.repositories.tenant_repo import TenantMemberRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_tenant_code

pytestmark = pytest.mark.blocking


# ---- 用例 12：Repository 缺租户上下文即抛错 ----


async def test_repository_requires_tenant_context(db_session: AsyncSession) -> None:
    repo = TenantMemberRepository(db_session)
    async with db_session.begin():
        with pytest.raises(RuntimeError, match="tenant context missing"):
            await repo.list_for_tenant(uuid.uuid4())


# ---- 用例 13：Repository 跨租户与不存在抛同一个 NotFound ----


async def test_repository_cross_tenant_and_missing_are_indistinguishable(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    a_id, b_id = two_tenants_with_members
    # 取 B 的成员 user_id
    async with tenant_transaction(db_session, b_id):
        result = await db_session.execute(text("SELECT user_id FROM tenant_members LIMIT 1"))
        b_user_id = result.scalar_one()

    repo = TenantMemberRepository(db_session)
    async with tenant_transaction(db_session, a_id):
        # require_membership：跨租户与不存在必须抛同一个 NotFound（坑 5）
        with pytest.raises(NotFoundError) as cross:
            await repo.require_membership(tenant_id=a_id, user_id=b_user_id)
        with pytest.raises(NotFoundError) as missing:
            await repo.require_membership(tenant_id=a_id, user_id=uuid.uuid4())
        # 可选查询则返回 None，服务层无从区分两种情况
        assert await repo.get_membership(tenant_id=a_id, user_id=b_user_id) is None
    assert cross.value.code == missing.value.code == 1004
    assert cross.value.message == missing.value.message


# ---- 用例 14：links 与 members 一致性 ----


async def test_link_table_consistency(db_session: AsyncSession) -> None:
    """业务写入路径必须双写（tenant_members + user_tenant_links）。"""
    from app.services.tenant_service import TenantService

    service = TenantService(db_session)
    async with db_session.begin():
        ta = Tenant(code=make_tenant_code("CONS"), name="CONS")
        db_session.add(ta)
        await db_session.flush()

    user_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:i, :e, 'x')"),
            {"i": str(user_id), "e": f"consistency{user_id}@t.io"},
        )
    async with tenant_transaction(db_session, ta.id):
        await service.members.add_member(tenant_id=ta.id, user_id=user_id, role="member")
        await service.links.add(user_id=user_id, tenant_id=ta.id, role="member")

    # 计数必须在租户上下文中做：tenant_members 走 RLS，无上下文时 fail-closed 返回 0 行
    async with tenant_transaction(db_session, ta.id):
        m = await db_session.execute(
            text("SELECT count(*) FROM tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": str(ta.id), "u": str(user_id)},
        )
        link = await db_session.execute(
            text("SELECT count(*) FROM user_tenant_links WHERE tenant_id = :t AND user_id = :u"),
            {"t": str(ta.id), "u": str(user_id)},
        )
        assert m.scalar_one() == link.scalar_one() == 1
