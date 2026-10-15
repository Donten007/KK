"""埋点服务：过滤 → 入库。**写入前过滤**是本模块存在的全部理由。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.analytics.guard import build_rows
from app.db.rls import tenant_transaction
from app.models.report_support import AnalyticsEvent
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        events: list[tuple[str, dict[str, object]]],
    ) -> dict[str, int]:
        """上报一批事件。tenant_id 来自 JWT（调用方无法伪造）。"""
        result = build_rows(events=events, tenant_id=tenant_id, user_id=user_id)
        if not result.accepted_rows:
            return result.as_dict()

        now = datetime.now(UTC)
        async with tenant_transaction(self.session, tenant_id):
            # append-only：只插不改不删（迁移里已 REVOKE UPDATE/DELETE）
            stmt = pg_insert(AnalyticsEvent).values(
                [
                    {**row, "occurred_at": now}
                    for row in result.accepted_rows
                ]
            )
            await self.session.execute(stmt)
        return result.as_dict()

    async def purge_expired(self, *, retention_days: int = 180) -> int:
        """物理删除超过保留期的事件（TRACKING-GUARD：180 天，无软删除语义）。

        【需资深】为什么逐租户删而不是一条跨租户 DELETE：
        analytics_events 有 RLS，本进程连接的是**非 BYPASSRLS 应用角色**，
        跨租户的 DELETE 会被策略过滤成 0 行（且不会报错——最危险的静默失败）。
        正确做法是遍历 tenants（该表无 RLS）后逐租户在自己的上下文里删。
        """
        from sqlalchemy import text

        tenant_rows = await self.session.execute(
            text("SELECT id FROM tenants WHERE status <> 'deleted'")
        )
        deleted_total = 0
        stmt = text(
            "DELETE FROM analytics_events "
            "WHERE occurred_at < now() - make_interval(days => CAST(:days AS int))"
        )
        for (tenant_id,) in tenant_rows.all():
            async with tenant_transaction(self.session, tenant_id):
                result = await self.session.execute(stmt, {"days": retention_days})
                deleted_total += int(getattr(result, "rowcount", 0) or 0)
        return deleted_total