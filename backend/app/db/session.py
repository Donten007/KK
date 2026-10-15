"""异步引擎与会话工厂。

引擎参数与 RLS 的配合点：
- pool_pre_ping：连接池复用前探测存活，避免拿到已被 PG 关闭的连接
- statement_timeout：单条语句硬超时，防慢查询拖垮共享库（SPEC §10.7）
- 应用连接角色在 .env 的 DATABASE_URL 中指定，必须非 superuser 且无 BYPASSRLS
  （dev 环境用 scripts/bootstrap_dev_db.sql 建角色）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import get_settings
from app.core.logging import get_logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = get_logger("db")

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_timeout=_settings.db_pool_timeout_seconds,
    pool_pre_ping=True,
    # 连接级 statement_timeout，与设置项联动（asyncpg 走 server_settings）
    connect_args={
        "server_settings": {
            "statement_timeout": str(_settings.db_statement_timeout_ms),
            "timezone": "UTC",
        },
        # 禁止 asyncpg 的类型缓存把 tenant GUC 相关计划钉死（ADR-003 负面项）
        "statement_cache_size": 500,
    },
    echo=False,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """独立会话作用域（后台任务 / 脚本用）。请求路径请走 api/deps.get_db。"""
    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()


async def dispose_engine() -> None:
    await engine.dispose()
    logger.info("db_engine_disposed")
