"""岗位模板与 AI 员工模型（SPEC §6.2）。

岗位模板是**平台级共享表**（无 RLS），但它携带四组技术字段，缺任一组
则 F6 与 F2 无法落地（SPEC §2.2 硬要求）：
  required_caps / optional_caps / expected_idle_steps / expected_total_steps
  baseline_minutes_per_run（ADR-015 ROI 折算参数，租户可覆盖）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """岗位模板（无 RLS，平台维护）。新岗位上线前必须补齐四组技术字段。"""

    __tablename__ = "job_templates"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Lucide 图标名（SPEC §8.6 唯一图标库；禁 emoji）
    icon: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)  # 一句话职责
    deliverables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    prerequisites: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    required_caps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    optional_caps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 无进展阈值（ADR-011 §3）：软阈值 = expected_idle_steps，硬阈值 = ×2
    expected_idle_steps: Mapped[int] = mapped_column(Integer, server_default=text("5"), nullable=False)
    expected_total_steps: Mapped[int] = mapped_column(Integer, server_default=text("12"), nullable=False)
    baseline_minutes_per_run: Mapped[int] = mapped_column(Integer, server_default=text("25"), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), server_default=text("'low'"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 步骤定义（steps_def）：F6-lite 图展开的依据
    steps_def: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI 员工（RLS 保护）。parent_id 自引用构成组织树，必须建索引。"""

    __tablename__ = "agents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    job_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_templates.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    permission_level: Mapped[str] = mapped_column(String(16), server_default=text("'member'"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    monthly_budget_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    spent_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 首次成功试跑时间：未试跑禁止开启定时（SPEC §5.2 端点 86）
    trial_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)