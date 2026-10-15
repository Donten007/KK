"""汇报与用量路由（只挂端点 + 接依赖）。

两个用量的 endpoint **刻意分开**（AC-14b / ADR-017）：
- `/usage/summary` → owner 口径，schema 内无 token 字段
- `/settings/usage` → admin 口径，含 token 明细

绝不用「同一 endpoint 按角色 oneOf」——那会让 token 出现在 owner 的响应 schema 里
只是被 controller 剔除，泄漏就退化为「每个人每次都记得剔除」。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthUser, TenantSession, require_role
from app.controllers import report as controller
from app.controllers import usage as usage_controller
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
usage_router = APIRouter(prefix="/api/v1", tags=["usage"])


@router.get("/daily")
async def daily_report(
    user: AuthUser,
    session: TenantSession,
    report_date: Annotated[date | None, Query(alias="date")] = None,
) -> ApiResponse:
    return await controller.daily(user, session, report_date)


@router.get("/daily/{report_date}")
async def daily_report_by_date(
    report_date: date, user: AuthUser, session: TenantSession
) -> ApiResponse:
    return await controller.daily(user, session, report_date)


@router.get("/weekly")
async def weekly_report(
    user: AuthUser,
    session: TenantSession,
    week_start: Annotated[date | None, Query()] = None,
) -> ApiResponse:
    return await controller.weekly(user, session, week_start)


@router.get("/cost-breakdown")
async def cost_breakdown(user: AuthUser, session: TenantSession) -> ApiResponse:
    return await controller.cost_breakdown(user, session)


@usage_router.get("/usage/summary", dependencies=[Depends(require_role("owner"))])
async def owner_usage(
    user: AuthUser,
    session: TenantSession,
    period: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> ApiResponse:
    return await usage_controller.owner_summary(user, session, period)


@usage_router.get("/settings/usage", dependencies=[Depends(require_role("admin"))])
async def admin_usage(
    user: AuthUser,
    session: TenantSession,
    period: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> ApiResponse:
    return await usage_controller.admin_summary(user, session, period)
