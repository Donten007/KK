"""users / auth_refresh_tokens 仓库。

users 表无 RLS（跨租户共享身份），方法不带 tenant_id；
auth_refresh_tokens 有 RLS，方法带 tenant_id 并走 _guard。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from app.models.user import RefreshToken, User
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class UserRepository:
    """身份仓库。users 无 RLS，但查询仍按 email 精确匹配，不做跨租户枚举暴露。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
        """批量查询（消除成员列表的 N+1）。"""
        if not user_ids:
            return {}
        result = await self.session.execute(select(User).where(User.id.in_(user_ids)))
        return {u.id: u for u in result.scalars().all()}

    async def create(self, *, email: str, password_hash: str, name: str | None = None) -> User:
        user = User(email=email, password_hash=password_hash, name=name)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    async def set_last_tenant(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(last_tenant_id=tenant_id)
        )


class RefreshTokenRepository:
    """refresh token 仓库（RLS 保护）。rotation 与重放检测的落点。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        row_id: uuid.UUID | None = None,
    ) -> RefreshToken:
        """row_id 显式传入时必须等于 JWT 的 jti（refresh 定位旧行靠它）。"""
        row = RefreshToken(
            id=row_id or uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_active_by_hash(
        self, *, tenant_id: uuid.UUID, token_hash: str
    ) -> RefreshToken | None:
        """只返回未吊销且未过期的行。RLS 保证 tenant_id 之外的租户不可见。"""
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.tenant_id == tenant_id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def get_any_by_hash(self, *, tenant_id: uuid.UUID, token_hash: str) -> RefreshToken | None:
        """不看过期/吊销状态——用于重放检测（已撤销 token 再次出现即告警）。"""
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.tenant_id == tenant_id,
                RefreshToken.token_hash == token_hash,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, *, row_id: uuid.UUID, replaced_by: uuid.UUID | None) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == row_id)
            .values(revoked_at=datetime.now(UTC), replaced_by=replaced_by)
        )

    async def revoke_all_for_user(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """重放检测命中：吊销该用户在该租户下的全部 refresh token（SPEC §4.3）。"""
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.tenant_id == tenant_id,
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            ),
        )
        return int(result.rowcount or 0)

    async def revoke_by_hash(self, *, tenant_id: uuid.UUID, token_hash: str) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.tenant_id == tenant_id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
