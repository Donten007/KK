"""用户资料服务（/auth/me）。"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError
from app.repositories.user_repo import UserRepository
from app.schemas.auth import UserOut
from sqlalchemy.ext.asyncio import AsyncSession


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)

    async def get_profile(self, user_id: uuid.UUID) -> UserOut:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError()
        return UserOut.model_validate(user)
