"""待确认队列与出网白名单模型（SPEC §6.2）。

pending_items 的 kind **只允许 needs_human_input**：熔断走任务行内联，
不进队列（ADR-018：混在一起会让老板错误归因「这个员工能力不行」，
而熔断时老板不需要做任何决定）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

PENDING_KINDS = ("needs_human_input",)


class PendingItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pending_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(32), server_default=text("'needs_human_input'"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 依据行：每条必须含（引用文件与位置），否则「问问题等于甩锅」
    evidence_ref: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # 停在哪一步（业务语言步骤标题，如「读取竞品页面 7/10」）——暂停那一刻写入，
    # 事后无法从 goal 反推（步骤标题可能随输入变化）
    stopped_step: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantEgressAllowlist(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """出网白名单（AC-B1）。status=pending 时该域名不可抓取。"""

    __tablename__ = "tenant_egress_allowlist"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), server_default=text("'public'"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsEvent(UUIDPrimaryKeyMixin, Base):
    """埋点事件（TRACKING-GUARD）。

    禁记项由写入前过滤保证（防线 3），本表只存已过滤的属性：
    IP / UA / 原始输入内容 / 文件名 一律不入库。
    保留 180 天，Hatchet cron 每日**物理删除**（无软删除语义）。
    """

    __tablename__ = "analytics_events"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )