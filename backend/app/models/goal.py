"""Goal 长任务三层状态模型（ADR-011）。

L3 业务层：Goal / TaskStep / TaskArtifact / GoalEvent / GoalProgressState
L2 执行层：LangGraph checkpointer（langgraph_checkpoints schema，不在本文件）
L1 正确性层：task_steps 的 PRIMARY KEY (goal_id, step_ordinal) 即幂等键

关键约束：
- F6-4：Goal.id 同时是 LangGraph 的 thread_id（用户刷新页面找不到自己的任务）
- 坑 10：stopping 是**独立状态**，不是 running + flag
- ADR-017：GoalEvent.visibility 默认 'admin'（fail-safe 方向）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ---- 状态枚举（openapi GoalStatus + stopping 独立态）----
GOAL_STATUSES = (
    "pending",
    "running",
    "stopping",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "expired",
)
# 中止相关终态：cancel 幂等判定必须把这些当作「已受理」
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "expired"})

STEP_STATUSES = ("pending", "running", "succeeded", "failed", "skipped")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    budget_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    spent_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    estimated_steps: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 归属岗位模板：无进展阈值从模板取，禁止硬编码（ADR-011 §3）
    job_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resumed_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    circuit_break_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 中止信号发出时刻：stopping 5 秒超时兜底据此收敛（ADR-017）
    stopping_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskStep(Base):
    """业务步骤（L3）。PRIMARY KEY 即幂等键，重放时 ON CONFLICT DO NOTHING。"""

    __tablename__ = "task_steps"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    step_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"), nullable=False)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 无进展检测用：最近 K 步的工具签名序列（JSON 数组，NULL 表示本步无工具调用）
    tool_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    delta_artifacts: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TaskArtifact(Base):
    """产出物登记表。content_hash 用于识别「改了又改回原样」的空转（ADR-011）。"""

    __tablename__ = "task_artifacts"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    step_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GoalEvent(Base):
    """事件流。visibility 默认 'admin'——新增事件忘记标 owner 时默认落安全侧（ADR-017）。"""

    __tablename__ = "goal_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    visibility: Mapped[str] = mapped_column(String(8), server_default=text("'admin'"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GoalProgressState(Base):
    """无进展检测窗口状态。必须落盘，否则崩溃重启归零，死循环重复触发 N 次（ADR-011 §5）。"""

    __tablename__ = "goal_progress_state"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    idle_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 最近 K 步的工具签名（JSON 字符串数组）
    recent_signatures: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # 已出现过的窗口哈希集合（JSON 字符串数组）
    seen_tool_windows: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    identical_signature_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    soft_pause_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )