"""Goal 控制器：参数 → 调 service → 组装信封。"""

from __future__ import annotations

import uuid

from app.api.deps import AuthUser, TenantSession
from app.schemas.common import ApiResponse, paged
from app.services.goal_service import GoalService
from pydantic import BaseModel, Field


class CreateGoalRequest(BaseModel):
    agent_id: uuid.UUID
    input: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    urls: list[str] = Field(default_factory=list, max_length=20)


async def create_goal(body: CreateGoalRequest, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    goal_id, estimate = await service.create(
        tenant_id=user.tenant_id,
        agent_id=body.agent_id,
        user_id=user.user_id,
        title=body.input,
        input_payload={"input": body.input, "urls": body.urls},
    )
    # 预估以**区间 + 偏差说明**返回，绝不冒充精确报价（坑 13 / AC-E3）
    return {
        "code": 0,
        "data": {
            "id": str(goal_id),
            "agent_id": str(body.agent_id),
            "status": "pending",
            "title": body.input[:200],
            "estimated_steps": estimate.steps,
            "estimated_cost_cents": estimate.cost_cents,
            "estimated_cost_low_cents": estimate.cost_low_cents,
            "estimated_cost_high_cents": estimate.cost_high_cents,
            "estimate_precision": estimate.precision,
            "estimate_caveats": list(estimate.caveats),
        },
        "message": "",
    }


async def get_goal(goal_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    data = await service.get_detail(
        tenant_id=user.tenant_id, goal_id=goal_id, role=user.role
    )
    return {"code": 0, "data": data, "message": ""}


async def cancel_goal(goal_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    result = await service.cancel(
        tenant_id=user.tenant_id, goal_id=goal_id, user_id=user.user_id
    )
    return {"code": 0, "data": result, "message": ""}


async def resume_goal(goal_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    result = await service.resume(
        tenant_id=user.tenant_id, goal_id=goal_id, user_id=user.user_id
    )
    return {"code": 0, "data": {**result, "id": str(goal_id)}, "message": ""}


async def list_steps(goal_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    steps = await service.list_steps(tenant_id=user.tenant_id, goal_id=goal_id)
    return {"code": 0, "data": steps, "message": ""}


async def list_events(goal_id: uuid.UUID, user: AuthUser, session: TenantSession) -> ApiResponse:
    service = GoalService(session)
    events = await service.list_events(
        tenant_id=user.tenant_id, goal_id=goal_id, role=user.role
    )
    return {"code": 0, "data": events, "message": ""}


async def list_goals(
    user: AuthUser,
    session: TenantSession,
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> ApiResponse:
    service = GoalService(session)
    items, total = await service.list_goals(
        tenant_id=user.tenant_id, page=page, limit=limit, status=status
    )
    return {"code": 0, "data": paged(items, total, page, limit), "message": ""}