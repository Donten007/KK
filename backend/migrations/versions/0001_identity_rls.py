"""初始迁移：身份与租户表 + RLS（SPEC §6.2 身份与租户 4 张 + audit_logs）。

RLS 分配（SPEC §6.1：除 users / model_capabilities / job_templates 外全部启用）：
- users：否（跨租户共享身份）
- tenants：否（账套注册表）
- user_tenant_links：否（登录解析索引，说明见模型 docstring）
- tenant_members：是
- auth_refresh_tokens：是
- audit_logs：是 + append-only

downgrade 必须可回滚（SPEC：每份迁移必须可回滚）。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls_ops import create_tenant_covering_index, create_tenant_isolation, make_append_only

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- users（无 RLS）----
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("email_verified", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("last_tenant_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- tenants（无 RLS）----
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(11), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plan", sa.String(16), server_default="trial", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("human_hourly_rate_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("tenant_dek", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenants_code", "tenants", ["code"], unique=True)

    # ---- tenant_members（RLS）----
    op.create_table(
        "tenant_members",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_pair"),
    )
    op.create_index("ix_tenant_members_tenant_id", "tenant_members", ["tenant_id"])
    op.create_index("ix_tenant_members_user_id", "tenant_members", ["user_id"])
    create_tenant_isolation(op, "tenant_members")

    # ---- user_tenant_links（无 RLS：登录解析索引，无业务数据）----
    op.create_table(
        "user_tenant_links",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant_links_pair"),
    )
    op.create_index("ix_user_tenant_links_user_id", "user_tenant_links", ["user_id"])
    op.create_index("ix_user_tenant_links_tenant_id", "user_tenant_links", ["tenant_id"])

    # ---- auth_refresh_tokens（RLS）----
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_refresh_tokens_tenant_id", "auth_refresh_tokens", ["tenant_id"])
    op.create_index("ix_auth_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])
    op.create_index(
        "uq_auth_refresh_tokens_token_hash", "auth_refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_auth_refresh_tokens_expires_at", "auth_refresh_tokens", ["expires_at"])
    create_tenant_isolation(op, "auth_refresh_tokens")

    # ---- audit_logs（RLS + append-only）----
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("level", sa.String(8), server_default="info", nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("result", sa.String(16), server_default="success", nullable=False),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    create_tenant_covering_index(op, "audit_logs")
    create_tenant_isolation(op, "audit_logs")
    make_append_only(op, "audit_logs")


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("user_tenant_links")
    op.drop_table("tenant_members")
    op.drop_table("tenants")
    op.drop_table("users")
