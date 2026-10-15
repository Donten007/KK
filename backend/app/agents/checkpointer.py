"""LangGraph Checkpointer 生命周期（ADR-011 L2 层）。

checkpointer 用 psycopg3 连接（langgraph-checkpoint-postgres 依赖它），
业务数据用 asyncpg 连接——两条连接线**故意分离**：
- 业务库：public schema，受 RLS 保护，连接角色非 superuser
- checkpoint 库：langgraph_checkpoints schema，LangGraph 官方 setup() 建表

连接串转换：把 postgresql+asyncpg:// 换成 postgresql://（psycopg 不认 +asyncpg）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("checkpointer")

# LangGraph 官方表所在 schema（SPEC §6.2「内部表，不手工改 schema」）
CHECKPOINT_SCHEMA = "langgraph_checkpoints"


def psycopg_conn_string() -> str:
    """把业务 DSN 转成 psycopg3 可用的 DSN，并固定 search_path。

    【需资深】为什么必须设 search_path：LangGraph 官方 setup() 的迁移 SQL 是
    **未带 schema 前缀**的（CREATE TABLE IF NOT EXISTS checkpoints ...），
    会落到连接的 search_path 首个 schema。我们把 search_path 固定为
    langgraph_checkpoints（迁移 0004 已建），从而：
    - checkpoint 表与应用业务表物理隔离
    - 应用角色对 public 无 CREATE 权限也不影响（最小权限边界成立）
    """
    url = get_settings().database_url
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options=-c%20search_path%3D{CHECKPOINT_SCHEMA}"


@asynccontextmanager
async def checkpoint_saver(*, setup: bool = False) -> AsyncIterator[Any]:
    """打开 checkpointer。

    setup=True 时执行 LangGraph 官方 setup() 建表（幂等）。
    【需资深】**不要在每次运行时 setup**：
    - 它会做 DDL，权限应由迁移预置（migrations/0004 建 schema + 授权）
    - 每个 run 调一次 setup 是纯粹的浪费
    正确用法：部署阶段跑一次 `python -m app.agents.checkpointer_bootstrap`，
    运行期用 setup=False。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conn_string = psycopg_conn_string()
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        if setup:
            await saver.setup()
            logger.info("checkpointer_setup_done", schema=CHECKPOINT_SCHEMA)
        yield saver


async def purge_thread_checkpoints(goal_id: str) -> None:
    """删除某 goal 的全部 checkpoint（AC-16 彻底删除的易漏项）。

    tenant 过滤依赖 thread_id == goal_id：goal_id 是我们生成的 UUID，
    外部无法构造他租户的 goal_id，因此按 thread_id 清理是安全的。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(psycopg_conn_string()) as saver:
        await saver.adelete_thread(goal_id)