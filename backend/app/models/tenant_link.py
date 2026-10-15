"""user_tenant_links：用户-账套关联索引（无 RLS）。

为什么需要它：tenant_members 有 RLS（SPEC §6.2），而登录发生在「还不知道
租户上下文」的时点——无上下文时 RLS fail-closed 返回 0 行，用户将被锁死
在自己所属的账套之外。本表承载登录解析所需的最小信息（user_id, tenant_id,
角色缓存），不含任何业务数据。

一致性保障：写入路径只有 tenant_service 的三个方法（add_member /
update_role / remove_member），且与 tenant_members 同一事务；
CI 断言两表行数按 tenant 一致（tests/security/test_link_consistency.py）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserTenantLink(Base):
    __tablename__ = "user_tenant_links"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant_links_pair"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # 角色缓存：与 tenant_members.role 同事务更新，仅供登录签发 token 用；
    # 权威来源仍是 tenant_members（管理端读取走 RLS 表）
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
