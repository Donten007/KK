"""迁移 0002：Goal 长任务与 F6-lite 检测窗口表（SPEC §6.2 Goal 与执行 6 张）。

全部启用 ENABLE + FORCE RLS（rls_ops.create_tenant_isolation）。
LangGraph checkpointer 表（langgraph_checkpoints schema）由 LangGraph 官方 setup()
创建，本文件不手工改其 schema（SPEC §6.2 明示），但 tenant_id 隔离在应用层通过
thread_id(=goal_id) 与 checkpointer 的独立 schema 策略保证（见 agent 运行时说明）。

downgrade 可回滚。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls_ops import create_tenant_covering_index, create_tenant_isolation

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("input_payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("budget_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("spent_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("estimated_steps", sa.Integer, server_default="0", nullable=False),
        sa.Column("estimated_cost_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("job_template_id", sa.String(64), nullable=True),
        sa.Column("resumed_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("circuit_break_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("stopping_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_goals_tenant_id", "goals", ["tenant_id"])
    op.create_index("ix_goals_agent_id", "goals", ["agent_id"])
    op.create_index("ix_goals_tenant_status", "goals", ["tenant_id", "status"])
    create_tenant_covering_index(op, "goals")
    create_tenant_isolation(op, "goals")

    op.create_table(
        "task_steps",
        sa.Column("goal_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("step_ordinal", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("output_ref", sa.Text, nullable=True),
        sa.Column("cost_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("model_id", sa.String(120), nullable=True),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("tool_signature", sa.Text, nullable=True),
        sa.Column("delta_artifacts", sa.Integer, server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKey("goals.id", ondelete="CASCADE"),
    )
    op.create_index("ix_task_steps_tenant_id", "task_steps", ["tenant_id"])
    op.create_index("ix_task_steps_tenant_status", "task_steps", ["tenant_id", "status"])
    create_tenant_covering_index(op, "task_steps")
    create_tenant_isolation(op, "task_steps")

    op.create_table(
        "task_artifacts",
        sa.Column("goal_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("artifact_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("step_ordinal", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKey("goals.id", ondelete="CASCADE"),
    )
    op.create_index("ix_task_artifacts_tenant_id", "task_artifacts", ["tenant_id"])
    create_tenant_covering_index(op, "task_artifacts")
    create_tenant_isolation(op, "task_artifacts")

    op.create_table(
        "goal_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("goal_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # ADR-017：默认 admin。新增事件忘记标 owner 时默认落安全侧。
        sa.Column("visibility", sa.String(8), server_default="admin", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKey("goals.id", ondelete="CASCADE"),
    )
    op.create_index("ix_goal_events_goal_seq", "goal_events", ["goal_id", "seq"])
    op.create_index("ix_goal_events_tenant_created", "goal_events", ["tenant_id", "created_at"])
    create_tenant_isolation(op, "goal_events")

    op.create_table(
        "goal_progress_state",
        sa.Column("goal_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("idle_streak", sa.Integer, server_default="0", nullable=False),
        sa.Column("recent_signatures", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("seen_tool_windows", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("identical_signature_streak", sa.Integer, server_default="0", nullable=False),
        sa.Column("soft_pause_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKey("goals.id", ondelete="CASCADE"),
    )
    op.create_index("ix_goal_progress_state_tenant_id", "goal_progress_state", ["tenant_id"])
    create_tenant_isolation(op, "goal_progress_state")


def downgrade() -> None:
    op.drop_table("goal_progress_state")
    op.drop_table("goal_events")
    op.drop_table("task_artifacts")
    op.drop_table("task_steps")
    op.drop_table("goals")