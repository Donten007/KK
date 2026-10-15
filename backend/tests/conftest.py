"""pytest 公共夹具。

数据库夹具策略：
- TEST_DATABASE_URL 未设置或不可达时，凡请求 db_session 的测试自动 skip
  （本地无 PostgreSQL 的开发机；CI 必须提供，门禁不得跳过——skip 带原因输出）
- 连接使用应用角色（opc_app，非 superuser 无 BYPASSRLS）——用超级用户连
  等于绕过 RLS，测了也白测（SPEC §9.7 用例 5 的出发点）
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 上 psycopg3 的异步模式不支持默认的 ProactorEventLoop
#（InterfaceError: cannot use the 'ProactorEventLoop' to run in async mode）。
# 必须在**任何事件循环创建之前**切换策略，因此放在模块导入期。
# 生产环境是 Linux，Selector 策略与其默认策略一致，不受影响。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://opc_app:opc_app_dev@localhost:5432/opcagentai_test",
)

# 在任何 app 模块导入前固定测试环境（app.config 在导入时读取 env）
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault(
    "DATABASE_MIGRATION_URL",
    os.environ.get(
        "TEST_MIGRATION_URL",
        "postgresql+asyncpg://opc_migrate:opc_migrate_dev@localhost:5432/opcagentai_test",
    ),
)
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-32")
os.environ.setdefault("CREDENTIAL_KEK", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("LOG_LEVEL", "WARNING")


def _db_reachable() -> bool:
    async def _probe() -> bool:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


DB_REACHABLE = _db_reachable()


@pytest.fixture(scope="session")
def db_url() -> str:
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """干净的应用角色会话（无租户上下文）。每个测试独立连接。

    数据库不可达时 skip（本地开发机无 PG；CI 必须提供实例）。
    """
    if not DB_REACHABLE:
        pytest.skip(f"PostgreSQL 不可达（{TEST_DATABASE_URL}），CI 环境必须提供")
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def make_tenant_code(tag: str) -> str:
    """测试用账套号：AC- + 8 位（hex 大写均在 Crockford 字母表内）。

    【需资深】注意不要用「固定前缀 + 3 位短随机」：3 位只有 12 bit，
    跑几百个用例后必然碰撞，表现为随机的 IntegrityError flaky，
    会让人误以为是产品缺陷（本次实测踩到）。
    """
    suffix = uuid.uuid4().hex[: 8 - len(tag)].upper()
    return f"AC-{tag}{suffix}"


@pytest_asyncio.fixture
async def two_tenants_with_members(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """造两个租户 A/B，各含一个 owner 成员。返回 (a_id, b_id)。"""
    from app.db.rls import tenant_transaction
    from app.models.tenant import Tenant, TenantMember

    a = Tenant(code=make_tenant_code("FIXA"), name="A")
    b = Tenant(code=make_tenant_code("FIXB"), name="B")
    user_a, user_b = uuid.uuid4(), uuid.uuid4()

    async with db_session.begin():
        db_session.add_all([a, b])
        await db_session.flush()
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash) VALUES "
                "(:ida, :ea, 'x'), (:idb, :eb, 'x')"
            ),
            {
                "ida": str(user_a),
                "ea": f"a{user_a}@t.io",
                "idb": str(user_b),
                "eb": f"b{user_b}@t.io",
            },
        )

    async with tenant_transaction(db_session, a.id):
        db_session.add(TenantMember(tenant_id=a.id, user_id=user_a, role="owner"))
    async with tenant_transaction(db_session, b.id):
        db_session.add(TenantMember(tenant_id=b.id, user_id=user_b, role="owner"))
    return a.id, b.id


@pytest.fixture(scope="session")
def api_client() -> TestClient:
    """会话级 TestClient。

    【需资深】为什么必须 session 级：app.db.session.engine 是模块级单例，
    asyncpg 连接池绑定在创建它的那个事件循环上。若每个测试文件各建一个
    TestClient，就会出现「旧循环已关闭、连接池仍被复用」→ RuntimeError:
    Event loop is closed（本次实测踩到）。单 client = 单循环 = 池可用。
    """
    if not DB_REACHABLE:
        pytest.skip("PostgreSQL 不可达，跳过 API 测试")
    from app.main import app

    with TestClient(app) as client:
        yield client
