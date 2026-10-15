"""SQLAlchemy 声明性基类与命名约定。

命名约定让 Alembic 自动生成迁移时约束名稳定（跨环境一致），
避免「本地能跑、staging 报 constraint 不存在」类问题。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class UUIDPrimaryKeyMixin:
    """UUID v4 主键（Python 侧生成，便于插入前已知 ID 供 RLS WITH CHECK 使用）。"""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """created_at / updated_at。时区强制 UTC（timestamptz）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin:
    """租户表标记 mixin：声明本表受 RLS 保护。

    每个租户表必须同时具备：
    1. tenant_id 列（本 mixin）
    2. 迁移中 ENABLE + FORCE ROW LEVEL SECURITY + 内联策略（migrations/rls_ops.py）
    两者缺一即失去隔离。CI 有 pg_policies 断言兜底（SPEC §9.7）。
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
