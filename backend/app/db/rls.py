"""租户上下文与事务作用域（ADR-003 四条硬规则的代码落地）。

R1 FORCE：迁移侧保证（见 migrations/rls_ops.py），此处不重复。
R2 内联策略：迁移侧保证。
R3 SET LOCAL：本文件的 set_config(..., true) —— 事务作用域，
   连接池复用不泄漏（SPEC 坑 4）。禁止用 SET（会话作用域）。
R4 视图 security_invoker：迁移侧保证。

fail-closed 语义（SPEC §4.4）：app.current_tenant 未设置时策略返回 NULL →
查询 0 行而非全部行。这是正确的安全默认，但会把「忘记设置上下文」伪装成
「列表页空了」。因此 _ensure_context 在检测到缺失时记录
level=WARNING, tag=tenant_context_missing 显式告警，不静默。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("tenant_ctx")

TENANT_GUC = "app.current_tenant"

# session 对象上标记「本事务已验证过租户上下文」的属性名。
# 每事务验证一次，避免每次仓库查询多一次往返（SPEC §10.3 P95 < 150ms）。
_VERIFIED_ATTR = "_opc_tenant_ctx_verified"


async def apply_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """在当前事务内设置租户上下文。必须在事务开始后调用（SET LOCAL 语义）。"""
    await session.execute(
        text("SELECT set_config(:guc, :tid, true)"),
        {"guc": TENANT_GUC, "tid": str(tenant_id)},
    )


async def current_tenant_setting(session: AsyncSession) -> str | None:
    """读取当前事务的租户上下文（第二个参数 true → 未设置返回 NULL 不报错）。"""
    result = await session.execute(
        text("SELECT current_setting(:guc, true)"), {"guc": TENANT_GUC}
    )
    value = result.scalar_one_or_none()
    return value if value else None


async def ensure_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """仓库层入口防御：确认会话租户上下文已设置且与显式传入的 tenant_id 一致。

    查询层防护（ADR-003 三层之一）：即使调用方漏了依赖注入直接建会话，
    这里也会拦下并告警。每事务只做一次实际查询，结果缓存在 session 对象上。
    """
    if getattr(session, _VERIFIED_ATTR, False):
        return

    actual = await current_tenant_setting(session)
    if actual is None:
        logger.warning(
            "tenant_context_missing",
            tag="tenant_context_missing",
            expected_tenant=str(tenant_id),
            hint="RLS 处于 fail-closed 状态，查询将返回 0 行；请检查会话是否经过 tenant_transaction",
        )
        raise RuntimeError(
            "tenant context missing: session 未设置 app.current_tenant，"
            "RLS fail-closed 将使查询返回 0 行（tag=tenant_context_missing）"
        )
    if actual != str(tenant_id):
        # 上下文与显式参数不一致：宁可拒绝也不放行——放行等于让两层防护互相矛盾
        logger.warning(
            "tenant_context_mismatch",
            tag="tenant_context_mismatch",
            session_tenant=actual,
            requested_tenant=str(tenant_id),
        )
        raise RuntimeError(
            f"tenant context mismatch: session={actual} requested={tenant_id}"
        )
    setattr(session, _VERIFIED_ATTR, True)


def clear_tenant_ctx_cache(session: AsyncSession) -> None:
    """事务结束后清除验证缓存（新事务必须重新验证，防止跨事务串味）。"""
    if hasattr(session, _VERIFIED_ATTR):
        delattr(session, _VERIFIED_ATTR)


@asynccontextmanager
async def work_unit(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """工作单元：正常退出提交，异常退出回滚。

    【需资深】为什么需要它：
    1. SQLAlchemy 的 autobegin 意味着**任何一次查询都会隐式开启事务**。
       若服务层无条件 `session.begin()`，而请求依赖层已开过事务（或服务自己
       先查再开），会抛 "A transaction is already begun on this Session"。
    2. 复用 autobegin 事务时**必须显式提交**：否则 session 关闭时静默回滚，
       业务写入凭空消失（本次实测：注册返回 201 但用户查不到）。

    语义统一为「工作单元」：进入时若无事务则开一个；退出时提交（异常则回滚）。
    嵌套调用是安全的——提交只是让已完成的工作落库，不会破坏外层一致性。
    """
    if session.in_transaction():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        await session.commit()
        return
    async with session.begin():
        yield session


@asynccontextmanager
async def tenant_scope(session: AsyncSession, tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """在**当前事务内**设置租户上下文（事务作用域，R3）。

    与 tenant_transaction 的区别：不再开事务，只切 GUC。
    适用场景：一个请求内先做无租户操作（users/tenants），拿到 tenant_id 后
    再写租户表（如注册：建完用户与账套才写成员）。
    """
    await apply_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        clear_tenant_ctx_cache(session)


@asynccontextmanager
async def tenant_transaction(
    session: AsyncSession, tenant_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """租户作用域事务：开事务（若尚未开启）+ 设置 GUC。"""
    async with work_unit(session), tenant_scope(session, tenant_id):
        yield session


@asynccontextmanager
async def plain_transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """无租户上下文的事务块。仅用于 users / tenants 等无 RLS 表。"""
    async with work_unit(session):
        yield session
