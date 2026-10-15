"""用量控制器：两个口径分两个方法，不接受 role 参数切换。

【需资深】不要把两个方法合并成 `_usage(role=...)`——那等于回到
「读了再剔除」，owner 的泄漏就退化成「每个人每次都记得剔除」。
"""

from __future__ import annotations

from app.api.deps import AuthUser, TenantSession
from app.schemas.common import ApiResponse, ok
from app.services.usage_service import UsageService


async def owner_summary(
    user: AuthUser, session: TenantSession, period: str | None
) -> ApiResponse:
    """owner 口径：OwnerUsageSchema，**无 token/model/duration 字段**。"""
    summary = await UsageService(session, user.tenant_id).owner_summary(period=period)
    return ok(summary.model_dump(mode="json"))


async def admin_summary(
    user: AuthUser, session: TenantSession, period: str | None
) -> ApiResponse:
    """admin 口径：AdminUsageSummary，含 token 明细。"""
    summary = await UsageService(session, user.tenant_id).admin_summary(period=period)
    return ok(summary.model_dump(mode="json"))
