"""tenants 表（账套，无 RLS）与 tenant_members 表（RLS 保护）。

账套号体系（ADR-003）：
- tenant_id：UUID v4，内部主键，数据库关联
- tenant_code：AC- + 8 位 Base32，对外账套号（客服/工单/登录场景可口述），
  不可枚举（40 bit）、不含业务信息、不可用于数据库关联
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)  # AC-XXXXXXXX
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(16), server_default=text("'trial'"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"), nullable=False)
    # ADR-015 ROI 折算参数（租户可覆盖，SPEC §4.7/§9 AC-E 系列）
    human_hourly_rate_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    # 每租户独立解密密钥（AC-15）：KEK 包裹的 DEK，base64。仅credentials 服务可读。
    tenant_dek: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenantMember(Base):
    """tenant_members（RLS 保护）。角色：owner(4) > admin(3) > member(2) > viewer(1)。"""

    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_pair"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # owner/admin/member/viewer
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
