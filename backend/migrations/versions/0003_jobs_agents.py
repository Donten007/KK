"""迁移 0003：岗位模板与 AI 员工（SPEC §6.2）。

job_templates 无 RLS（平台维护）；agents 启用 ENABLE + FORCE RLS。
downgrade 可回滚。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls_ops import create_tenant_covering_index, create_tenant_isolation

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # job_templates：平台级共享表，不启用 RLS
    op.create_table(
        "job_templates",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("icon", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(200), nullable=False),
        sa.Column("deliverables", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("prerequisites", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("required_caps", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("optional_caps", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_idle_steps", sa.Integer, server_default="5", nullable=False),
        sa.Column("expected_total_steps", sa.Integer, server_default="12", nullable=False),
        sa.Column("baseline_minutes_per_run", sa.Integer, server_default="25", nullable=False),
        sa.Column("difficulty", sa.String(16), server_default="low", nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("steps_def", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_templates_code", "job_templates", ["code"], unique=True)
    op.create_index("ix_job_templates_sort_order", "job_templates", ["sort_order"])

    # agents：租户表，启用 FORCE RLS
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "job_template_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("job_templates.id"),
            nullable=False,
        ),
        # parent_id 自引用：组织树查询必须走索引（SPEC §6.2）
        sa.Column("parent_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("permission_level", sa.String(16), server_default="member", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(120), nullable=True),
        sa.Column("monthly_budget_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("spent_cents", sa.Integer, server_default="0", nullable=False),
        sa.Column("trial_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])
    op.create_index("ix_agents_parent_id", "agents", ["parent_id"])
    op.create_index("ix_agents_job_template_id", "agents", ["job_template_id"])
    op.create_index("ix_agents_tenant_status", "agents", ["tenant_id", "status"])
    create_tenant_covering_index(op, "agents")
    create_tenant_isolation(op, "agents")


def downgrade() -> None:
    op.drop_table("agents")
    op.drop_table("job_templates")