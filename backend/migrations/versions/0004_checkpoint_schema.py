"""迁移 0004：LangGraph checkpoint schema 与权限预置。

【需资深】为什么单独一个迁移：
1. checkpoint 表由 LangGraph 官方 setup() 创建，**禁止手工改它的 schema**
   （SPEC §6.2）。但 schema 本身与访问权限必须由迁移预置，否则应用角色
   在运行时因「对模式 public 权限不够」而无法自举。
2. 应用角色只拿到该 schema 的 USAGE + CREATE，不给 public 的 DDL 权限——
   最小权限边界。

隔离说明（诚实记录，不是「已实现 RLS」）：
checkpoints 表的隔离依赖 **thread_id == goal_id**（UUID v4 不可枚举，
F6-4 要求）。checkpoint schema 内的表**未启用 RLS**——LangGraph 的连接
不携带租户 GUC，强加策略会与其官方 schema 冲突。AC-16 彻底删除时按
thread_id 清理（app.agents.checkpointer.purge_thread_checkpoints）。
若后续要求 checkpoint 表也走 RLS，需在 Phase 3 与 checkpointer 连接层
一并设计（给该连接单独设置 app.current_tenant）。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKPOINT_SCHEMA = "langgraph_checkpoints"
APP_ROLE = "opc_app"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}')
    # 角色可能尚未创建（首次引导顺序），故用 DO 块容错
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT USAGE, CREATE ON SCHEMA {CHECKPOINT_SCHEMA} TO {APP_ROLE};
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {CHECKPOINT_SCHEMA} CASCADE")