"""users 表（无 RLS，可跨租户）。

last_tenant_id：用户「当前账套」指针。登录时签发该账套作用域的 token；
切换账套（POST /tenants/current/switch）更新此列并签发新 token。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    last_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:  # 禁止把邮箱整体打进日志的兜底（日志层另有 redaction）
        return f"<User id={self.id}>"


class RefreshToken(Base):
    """auth_refresh_tokens（RLS 保护，tenant_id 决定可见性）。

    设计要点：
    - token_hash 存 SHA-256 Hex，明文不落库（SPEC §4.3）
    - rotation：每次刷新旧行 revoked_at=now() + replaced_by=新行 id
    - 重放检测：已 revoked 的 token 再次出现 → 吊销该用户全部 refresh token
    - tenant_id 让本表可走统一 RLS；refresh 流程先由 JWT 解出 tenant_id 再查库
    """

    __tablename__ = "auth_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
