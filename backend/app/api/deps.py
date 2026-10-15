"""FastAPI 依赖注入：数据库会话（带租户上下文）、当前用户、角色守卫。

依赖方向：api → controllers → services → repositories（只向下）。
本文件是 api 层与 db/core 层的唯一接缝：控制器不直接建会话。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.security import decode_token
from app.db.rls import tenant_transaction
from app.db.session import AsyncSessionFactory

ROLE_RANK = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}


class CurrentUser(BaseModel):
    """从 access token 解析的调用方身份。tenant_id 来自 JWT，不接受请求体传入。"""

    model_config = {"frozen": True}

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


async def get_plain_session() -> AsyncIterator[AsyncSession]:
    """无租户上下文的会话。**本依赖不持有事务**，事务由 service 的 work_unit /
    tenant_transaction 自行管理。

    【需资深】为什么这里不能像 TenantSession 那样把事务提到依赖层：
    一旦依赖持有事务，**任何错误响应都会让整个请求事务回滚**——包括那些
    「先做安全动作、再抛错」的路径。实测踩到：refresh 重放检测先吊销该用户
    全部 token 再抛 401，吊销被自己的异常回滚掉，重放后 token 仍然可用。
    认证链路的每一步都必须自己决定何时提交，故依赖层让出事务所有权。
    """
    async with AsyncSessionFactory() as session:
        yield session


async def get_current_user(
    request: Request, authorization: str = Header(default="")
) -> CurrentUser:
    if not authorization.startswith("Bearer "):
        raise UnauthenticatedError()
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise UnauthenticatedError()
    payload = decode_token(token, expected_type="access")
    user = CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        tenant_id=uuid.UUID(payload["tenant_id"]),
        role=str(payload.get("role", "member")),
    )
    # 挂到 request.state 供异常处理器记录安全日志（跨租户拒绝审计，SPEC §4.4）
    request.state.current_user = user
    return user


async def get_tenant_session(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> AsyncIterator[AsyncSession]:
    """请求级租户会话：事务开始即 SET LOCAL app.current_tenant（R3）。
    整个请求处理在同一事务内，提交后 GUC 随事务结束失效，连接池复用不泄漏。"""
    async with AsyncSessionFactory() as session, tenant_transaction(session, user.tenant_id):
        yield session


def require_role(min_role: str) -> Callable[..., Awaitable[CurrentUser]]:
    """角色守卫：租户内权限不足 → 403（1003）。跨租户场景禁止使用（一律 404）。"""

    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK.get(min_role, 99):
            raise ForbiddenError()
        return user

    return checker


# 常用会话类型别名
PlainSession = Annotated[AsyncSession, Depends(get_plain_session)]
TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]
AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
