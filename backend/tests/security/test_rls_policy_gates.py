"""阻断级：RLS 策略与结构门禁（SPEC §9.7 用例 5/7/8/10 + ADR-003 硬规则 R1/R2/R4）。

这几条是数据库级断言：不构造业务数据，直接检查 pg_class / pg_policies /
权限位——防的是「有人新建表忘了开 RLS」与「有人把策略改成函数调用」。
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.db.rls import tenant_transaction
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.blocking

TENANT_TABLES = ["tenant_members", "auth_refresh_tokens", "audit_logs"]


# ---- 用例 9（R1）：全部租户表 ENABLE + FORCE ----


async def test_all_tenant_tables_have_enable_and_force_rls(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(:names)"
        ),
        {"names": TENANT_TABLES},
    )
    rows = {r[0]: (r[1], r[2]) for r in result.all()}
    for table in TENANT_TABLES:
        assert table in rows, f"{table} 不存在"
        assert rows[table] == (True, True), f"{table} 必须 ENABLE + FORCE RLS（R1）"


# ---- 用例 10（R2）：策略全部内联式，无函数调用形态 ----


async def test_policies_are_inline_not_function_calls(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text("SELECT tablename, qual, with_check FROM pg_policies WHERE tablename = ANY(:names)"),
        {"names": TENANT_TABLES},
    )
    for table, qual, with_check in result.all():
        for expr in (qual, with_check):
            assert "current_setting" in expr, f"{table} 策略缺少 current_setting"
            assert "NULLIF(" in expr, f"{table} 策略必须内联 NULLIF（R2）"
            assert "app_current_tenant" not in expr, f"{table} 禁止 PL/pgSQL 辅助函数（R2）"


# ---- 用例 11：audit_logs append-only ----


async def test_audit_logs_append_only_for_app_role(db_session: AsyncSession) -> None:
    """应用角色对 audit_logs 只允许 INSERT/SELECT，禁止 UPDATE/DELETE（SPEC §6.2）。"""
    for op_name, allowed in (("INSERT", True), ("SELECT", True), ("UPDATE", False), ("DELETE", False)):
        result = await db_session.execute(
            text("SELECT has_table_privilege(current_user, 'audit_logs', :op)"), {"op": op_name}
        )
        assert result.scalar_one() is allowed, (
            f"audit_logs 对应用角色的 {op_name} 权限应为 {allowed}（append-only 约束）"
        )


# ---- 用例 7：表 owner 不能绕过（FORCE 生效）----


async def test_table_owner_cannot_bypass_force_rls(
    db_session: AsyncSession, two_tenants_with_members
) -> None:
    migration_url = os.environ.get("TEST_MIGRATION_URL")
    if not migration_url:
        pytest.skip("TEST_MIGRATION_URL 未提供（owner 角色连接串）")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(migration_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with factory() as owner_session:
            a_id, b_id = two_tenants_with_members
            async with tenant_transaction(owner_session, a_id):
                result = await owner_session.execute(
                    text("SELECT count(*) FROM tenant_members WHERE tenant_id = :tid"),
                    {"tid": str(b_id)},
                )
                assert result.scalar_one() == 0, "FORCE RLS 未生效：表 owner 绕过了隔离"
    finally:
        await engine.dispose()


# ---- 用例 8（R4）：视图受 RLS 约束 ----


async def test_views_respect_rls(db_session: AsyncSession, two_tenants_with_members) -> None:
    migration_url = os.environ.get("TEST_MIGRATION_URL")
    if not migration_url:
        pytest.skip("TEST_MIGRATION_URL 未提供（建视图需要 DDL 权限）")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migration_url)
    view_name = f"v_test_members_{uuid.uuid4().hex[:6]}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE VIEW {view_name} WITH (security_invoker = true) "
                "AS SELECT * FROM tenant_members"
            )
        )
    try:
        a_id, b_id = two_tenants_with_members
        async with tenant_transaction(db_session, a_id):
            result = await db_session.execute(
                text(f"SELECT count(*) FROM {view_name} WHERE tenant_id = :tid"),
                {"tid": str(b_id)},
            )
            assert result.scalar_one() == 0, "视图绕过 RLS（缺 security_invoker）"
        # R4：public schema 全部视图必须显式 security_invoker=true
        async with db_session.begin():
            rows = await db_session.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind = 'v' AND n.nspname = 'public' "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM pg_options_to_table(c.reloptions) o "
                    "  WHERE o.option_name = 'security_invoker' AND o.option_value = 'true')"
                )
            )
            offenders = [r[0] for r in rows.all()]
            assert offenders == [], f"以下视图缺少 security_invoker=true：{offenders}"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
        await engine.dispose()
