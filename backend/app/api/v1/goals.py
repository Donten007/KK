"""Goal 路由（只挂端点 + 接依赖）。

角色：member 及以上（SPEC §5.2 端点 87-93）。
cancel / resume 幂等：重复调用返回同一状态不报错（ADR-017）。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AuthUser, TenantSession
from app.controllers import goal as controller
from app.controllers.goal import CreateGoalRequest
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


@router.get("")
async def list_goals(
    user: AuthUser,
    session: TenantSession,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: str | None = None,
) -> ApiResponse:
    return await controller.list_goals(user, session, page, limit, status)


@router.post("", status_code=202)
async def create_goal(
    body: CreateGoalRequest, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.create_goal(body, user, session)


@router.get("/{goal_id}")
async def get_goal(
    goal_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.get_goal(goal_id, user, session)


@router.post("/{goal_id}/cancel")
async def cancel_goal(
    goal_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.cancel_goal(goal_id, user, session)


@router.post("/{goal_id}/resume", status_code=202)
async def resume_goal(
    goal_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.resume_goal(goal_id, user, session)


@router.get("/{goal_id}/steps")
async def list_steps(
    goal_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.list_steps(goal_id, user, session)


@router.get("/{goal_id}/events")
async def list_events(
    goal_id: uuid.UUID, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.list_events(goal_id, user, session)
