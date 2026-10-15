"""迁移 0005：用量计价 + 出网白名单 + 待确认队列 + 埋点（SPEC §6.2）。

RLS 分配：
- model_pricing：否（平台级）
- usage_events / usage_records / usage_daily：是
- tenant_egress_allowlist / pending_items / analytics_events：是

audit_logs 的 REVOKE 在 0001 已做（app_role 不存在时跳过），此处对
analytics_events 同样只插不改不删（埋点数据是事实记录）。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls_ops import create_tenant_covering_index, create_tenant_isolation, make_append_only

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- usage_events（幂等键 = tenant_id + request_id）----
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("goal_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("cache_hit_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_usage_events_request"),
    )
    op.create_index("ix_usage_events_tenant_id", "usage_events", ["tenant_id"])
    op.create_index("ix_usage_events_tenant_occurred", "usage_events", ["tenant_id", "occurred_at"])
    create_tenant_isolation(op, "usage_events")

    # ---- usage_records（小时聚合，owner 口径不读）----
    op.create_table(
        "usage_records",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("call_count", sa.Integer, server_default="0", nullable=False),
    )
    op.create_index("ix_usage_records_tenant_id", "usage_records", ["tenant_id"])
    op.create_index("ix_usage_records_tenant_bucket", "usage_records", ["tenant_id", "bucket_hour"])
    op.create_index("ix_usage_records_tenant_agent", "usage_records", ["tenant_id", "agent_id"])
    create_tenant_isolation(op, "usage_records")

    # ---- usage_daily（owner 口径唯一成本源）----
    op.create_table(
        "usage_daily",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_day", sa.Date, nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("cost_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("call_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("task_count", sa.Integer, server_default="0", nullable=False),
    )
    op.create_index("ix_usage_daily_tenant_id", "usage_daily", ["tenant_id"])
    op.create_index("ix_usage_daily_tenant_day", "usage_daily", ["tenant_id", "bucket_day"])
    create_tenant_isolation(op, "usage_daily")

    # ---- model_pricing（平台级，无 RLS）----
    op.create_table(
        "model_pricing",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("price_in_cents_per_mtok", sa.Integer, nullable=False),
        sa.Column("price_out_cents_per_mtok", sa.Integer, nullable=False),
        sa.Column("source", sa.String(32), server_default="litellm", nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_pricing_provider_model", "model_pricing", ["provider", "model_id"])

    # ---- tenant_egress_allowlist（AC-B1 站点准入）----
    op.create_table(
        "tenant_egress_allowlist",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(16), server_default="public", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("reviewed_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_egress_allowlist_tenant_id", "tenant_egress_allowlist", ["tenant_id"])
    op.create_index(
        "ix_tenant_egress_allowlist_tenant_status", "tenant_egress_allowlist", ["tenant_id", "status"]
    )
    op.create_index("ix_tenant_egress_allowlist_domain", "tenant_egress_allowlist", ["domain"])
    create_tenant_covering_index(op, "tenant_egress_allowlist")
    create_tenant_isolation(op, "tenant_egress_allowlist")

    # ---- pending_items（待确认队列，**只含 needs_human_input**）----
    op.create_table(
        "pending_items",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        # kind 恒为 needs_human_input：circuit_break 走任务行内联，不进队列（ADR-018）
        sa.Column("kind", sa.String(32), server_default="needs_human_input", nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # 依据行：每条必须含，否则「问问题等于甩锅」（SPEC §7.4）
        sa.Column("evidence_ref", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pending_items_tenant_id", "pending_items", ["tenant_id"])
    op.create_index("ix_pending_items_tenant_status", "pending_items", ["tenant_id", "status"])
    create_tenant_covering_index(op, "pending_items")
    create_tenant_isolation(op, "pending_items")

    # ---- analytics_events（埋点，180 天物理删除）----
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        # 列名 event 与 openapi 契约一致（不是 event_name）
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("properties", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_analytics_events_tenant_id", "analytics_events", ["tenant_id"])
    op.create_index(
        "ix_analytics_events_tenant_occurred", "analytics_events", ["tenant_id", "occurred_at"]
    )
    op.create_index("ix_analytics_events_event", "analytics_events", ["event"])
    create_tenant_isolation(op, "analytics_events")
    make_append_only(op, "analytics_events")


def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("pending_items")
    op.drop_table("tenant_egress_allowlist")
    op.drop_table("model_pricing")
    op.drop_table("usage_daily")
    op.drop_table("usage_records")
    op.drop_table("usage_events")