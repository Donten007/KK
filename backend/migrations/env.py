"""Alembic 环境配置。

两个连接角色分离（SPEC §4.4 实现约束：应用连接角色非 superuser 无 BYPASSRLS）：
- 迁移用 DATABASE_MIGRATION_URL（opc_migrate，可 DDL）
- 应用运行时用 DATABASE_URL（opc_app，只 DML）

env.py 从 app.config 读 URL，不依赖 alembic.ini 的 sqlalchemy.url，
避免连接串散落两处（code-organization 规则 8）。
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.base import Base
import app.models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 迁移引擎 URL（DDL 角色）
config.set_main_option("sqlalchemy.url", get_settings().database_migration_url)


def _include_object(object_, name, type_, reflected, compare_to):
    """RLS 策略不在 metadata 中，由迁移文件显式创建，autogen 不管。"""
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda conn: context.configure(
                connection=conn,
                target_metadata=target_metadata,
                include_object=_include_object,
                compare_type=True,
                transaction_per_migration=True,
            )
        )
        await connection.run_sync(lambda conn: context.run_migrations())
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
