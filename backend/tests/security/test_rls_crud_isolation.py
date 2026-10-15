"""阻断级：RLS CRUD 隔离测试（SPEC §9.7 用例 1-6 / ADR-003 Verification 步骤 1-6）。

连接身份必须是应用角色（opc_app，非 superuser 无 BYPASSRLS）——
用超级用户连等于绕过 RLS，测试失去意义。
"""

from __future__ import annotations

import uuid

import pytest
from app.db.rls import tenant_transaction
from app.models.tenant import Tenant, TenantMember
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import make_tenant_code

pytestmark = pytest.mark.blocking


async def _count_members(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    async with tenant_transaction(session, tenant_id):
        result = await session.execute(text("SELECT count(*) FROM tenant_members"))
        return int(result.scalar_one())


# ---- 用例 1：跨租户 SELECT 返回 0 行 ----


async def test_cross_tenant_select_returns_zero_rows(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    a_id, b_id = two_tenants_with_members
    # A 的上下文里显式查 B 的 tenant_id → RLS 必须过滤为 0 行
    async with tenant_transaction(db_session, a_id):
        result = await db_session.execute(
            text("SELECT count(*) FROM tenant_members WHERE tenant_id = :tid"),
            {"tid": str(b_id)},
        )
        assert result.scalar_one() == 0
    # 正向：A 能看到自己的
    assert await _count_members(db_session, a_id) == 1


# ---- 用例 2：跨租户 INSERT 被拒 ----


async def test_cross_tenant_insert_rejected(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    a_id, b_id = two_tenants_with_members
    # 取 B 已有的成员 user_id：FK 必须先满足，否则报 FK 违规而非 RLS 策略违规，
    # 测到的就不是隔离而是外键
    async with tenant_transaction(db_session, b_id):
        existing_user = (
            await db_session.execute(text("SELECT user_id FROM tenant_members LIMIT 1"))
        ).scalar_one()

    async with tenant_transaction(db_session, a_id):
        with pytest.raises(ProgrammingError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO tenant_members (id, tenant_id, user_id, role) "
                    "VALUES (gen_random_uuid(), :tid, :uid, 'member')"
                ),
                {"tid": str(b_id), "uid": str(existing_user)},
            )
        # 断言 SQLSTATE 而非错误文案：PG 错误消息随 lc_messages 变中文/英文，
        # 文案断言会在非英文环境下假绿（本次实测踩到）
        sqlstate = getattr(exc_info.value.orig, "sqlstate", None) or getattr(
            exc_info.value.orig, "pgcode", None
        )
        assert sqlstate == "42501", f"期望 RLS 策略违规(42501)，实际 {sqlstate}: {exc_info.value}"


# ---- 用例 3：跨租户 UPDATE 0 行 ----


async def test_cross_tenant_update_affects_zero_rows(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    a_id, b_id = two_tenants_with_members
    async with tenant_transaction(db_session, a_id):
        result = await db_session.execute(
            text("UPDATE tenant_members SET role = 'viewer' WHERE tenant_id = :tid"),
            {"tid": str(b_id)},
        )
        assert result.rowcount == 0


# ---- 用例 4：跨租户 DELETE 0 行 ----


async def test_cross_tenant_delete_affects_zero_rows(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    a_id, b_id = two_tenants_with_members
    async with tenant_transaction(db_session, a_id):
        result = await db_session.execute(
            text("DELETE FROM tenant_members WHERE tenant_id = :tid"), {"tid": str(b_id)}
        )
        assert result.rowcount == 0
    # B 的成员仍在
    assert await _count_members(db_session, b_id) == 1


# ---- 用例 5：无租户上下文 fail-closed ----


async def test_missing_tenant_context_fails_closed(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    """不设 app.current_tenant → 0 行（不是全部行）。表里有数据时该断言才有区分力。"""
    async with db_session.begin():
        result = await db_session.execute(text("SELECT count(*) FROM tenant_members"))
        assert result.scalar_one() == 0


# ---- 用例 6：SET LOCAL 不泄漏（连接池串味）----


async def test_set_local_does_not_leak_across_transactions(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ta = Tenant(code=make_tenant_code("LEAK"), name="LA")
        db_session.add(ta)
        user_id = uuid.uuid4()
        await db_session.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:i, :e, 'x')"),
            {"i": str(user_id), "e": f"leak{user_id}@t.io"},
        )
        await db_session.flush()

    async with tenant_transaction(db_session, ta.id):
        db_session.add(TenantMember(tenant_id=ta.id, user_id=user_id, role="owner"))
        await db_session.flush()

    # 同一物理连接，不开新上下文直接查 → 必须 0 行（SET LOCAL 随事务结束失效）
    async with db_session.begin():
        result = await db_session.execute(text("SELECT count(*) FROM tenant_members"))
        assert result.scalar_one() == 0

    assert await _count_members(db_session, ta.id) == 1
