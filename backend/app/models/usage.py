"""用量与成本聚合模型（SPEC §6.2 用量与计价）。

纯 BYOK 语义（ADR-019）：平台不经手资金，这两张表不是「计费流水」，
而是**客户成本可见性**——客户只有厂商的月度总额，我们给按岗位/员工下钻。

幂等是这里的最高优先级（SPEC §4.7 幂等条）：代付时代重复记账坑平台的钱，
纯 BYOK 时代重复记账坑的是**客户对平台的信任**。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsageEvent(Base):
    """单次 LLM 调用的 usage（来自厂商响应，不来自我们的账本）。

    request_id 是幂等键：同一请求重复投递（Redis 消费者重投）只入一行。
    """

    __tablename__ = "usage_events"
    __table_args__ = (UniqueConstraint("tenant_id", "request_id", name="uq_usage_events_request"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class UsageRecord(Base):
    """小时聚合（成本归集的权威表）。owner 口径**不读**本表的 token 字段。"""

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    bucket_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)


class UsageDaily(Base):
    """日聚合。**owner 口径的唯一成本数据源**（AC-C6：不 join token 字段）。"""

    __tablename__ = "usage_daily"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    bucket_day: Mapped[date] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)


class ModelPricing(Base):
    """LiteLLM 价格表落地（平台级，无 RLS）。每日同步 + 本地快照兜底。"""

    __tablename__ = "model_pricing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    price_in_cents_per_mtok: Mapped[int] = mapped_column(Integer, nullable=False)
    price_out_cents_per_mtok: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), server_default=text("'litellm'"), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
