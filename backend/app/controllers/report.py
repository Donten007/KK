"""汇报控制器：参数 → 调 service → 组装信封。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.api.deps import AuthUser, TenantSession
from app.core.errors import ValidationError
from app.schemas.common import ApiResponse, ok
from app.services.report_service import ReportService
from app.services.weekly_report import WeeklyReportService

# 回看窗口上限（SPEC §10.5）
MAX_LOOKBACK_DAYS = 30


async def daily(
    user: AuthUser, session: TenantSession, report_date: date | None
) -> ApiResponse:
    """今日汇报或指定日期。超出 30 天回看窗口即阻断。"""
    today = datetime.now(UTC).date()
    target = report_date or today
    if target > today:
        raise ValidationError("不能查看未来日期的汇报")
    if (today - target).days > MAX_LOOKBACK_DAYS:
        raise ValidationError(f"只能回看最近 {MAX_LOOKBACK_DAYS} 天的汇报")
    report = await ReportService(session, user.tenant_id).daily(report_date=target)
    return ok(report.model_dump(mode="json"))


async def weekly(
    user: AuthUser, session: TenantSession, week_start: date | None
) -> ApiResponse:
    report = await WeeklyReportService(session, user.tenant_id).weekly(week_start=week_start)
    return ok(report.model_dump(mode="json"))


async def cost_breakdown(user: AuthUser, session: TenantSession) -> ApiResponse:
    breakdown = await WeeklyReportService(session, user.tenant_id).cost_breakdown()
    return ok(breakdown.model_dump(mode="json"))
