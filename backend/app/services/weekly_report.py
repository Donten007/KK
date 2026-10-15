"""周报与员工维度成本构成（与日报分开：两者口径与消费者都不同）。

周报与日报的关键差异：**必须显示积压**（SPEC §7.4 / openapi WeeklyReport）——
日清模式会系统性掩盖慢性问题：老板每天处理 1 件、每周新增 8 件，
日报每天显示「1 件」看起来可控，周报显示「5 件积压，最早已等 3 天」才是真实信号。

统计区间 = 本周新增 + 期末仍未处理（不是仅本周新增）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.db.rls import tenant_transaction
from app.models.job import Agent
from app.models.report_support import PendingItem
from app.models.usage import UsageDaily
from app.schemas.report import (
    BacklogItem,
    CostBreakdown,
    CostBreakdownItem,
    TrustSummary,
    WeeklyReport,
)
from app.services.trust_metrics import count_escalations_and_resolutions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class WeeklyReportService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def weekly(self, *, week_start: date | None = None) -> WeeklyReport:
        """周报。与日报的关键差异：**必须显示积压**（日清会掩盖慢性问题）。"""
        start = week_start or (datetime.now(UTC).date() - timedelta(days=7))
        end = start + timedelta(days=6)

        async with tenant_transaction(self.session, self.tenant_id):
            backlog_rows = (
                await self.session.execute(
                    select(PendingItem, Agent)
                    .join(Agent, Agent.id == PendingItem.agent_id)
                    .where(
                        PendingItem.tenant_id == self.tenant_id,
                        PendingItem.status == "pending",
                    )
                    .order_by(PendingItem.created_at)
                )
            ).all()
            today = datetime.now(UTC).date()
            escalated, resolved = await count_escalations_and_resolutions(
                self.session, tenant_id=self.tenant_id, since=start
            )

        backlog = [
            BacklogItem(
                pending_id=str(row.PendingItem.id),
                agent_id=str(row.Agent.id),
                agent_name=row.Agent.name,
                reason=str(row.PendingItem.payload.get("reason", "")),
                waiting_days=(today - row.PendingItem.created_at.date()).days,
                created_at=row.PendingItem.created_at,
            )
            for row in backlog_rows
        ]
        unresolved = escalated - resolved
        return WeeklyReport(
            week_start=start,
            week_end=end,
            agents=[],
            backlog_count=len(backlog),
            # 禁止折叠：waiting_days 是升级信号
            backlog_items=backlog,
            trust_summary=TrustSummary(
                escalated_count=escalated,
                resolved_count=resolved,
                unresolved_count=unresolved,
                main_sentence=(
                    f"本周停下来问过 {escalated} 次，其中 {unresolved} 次还在等你。"
                    if unresolved
                    else f"本周停下来问过 {escalated} 次，每次你都做了决定。它们没有一次是猜的。"
                ),
                all_resolved=unresolved == 0,
            ),
            roi={"baseline_configured": False},
        )

    async def cost_breakdown(self, *, month: date | None = None) -> CostBreakdown:
        """员工维度成本构成（业务口径，**无 token**）。"""
        anchor = month or datetime.now(UTC).date()
        start, end = anchor.replace(day=1), _month_end(anchor)
        async with tenant_transaction(self.session, self.tenant_id):
            rows = (
                await self.session.execute(
                    select(UsageDaily.agent_id, func.sum(UsageDaily.cost_cents),
                           func.sum(UsageDaily.task_count))
                    .where(
                        UsageDaily.tenant_id == self.tenant_id,
                        UsageDaily.bucket_day >= start,
                        UsageDaily.bucket_day <= end,
                    )
                    .group_by(UsageDaily.agent_id)
                )
            ).all()
            agents = (
                await self.session.execute(
                    select(Agent.id, Agent.name).where(Agent.tenant_id == self.tenant_id)
                )
            ).all()
        names = dict(agents)
        items = [
            CostBreakdownItem(
                agent_id=str(row[0]),
                agent_name=names.get(row[0], "未命名员工"),
                task_count=int(row[2] or 0),
                cost_cents=int(row[1] or 0),
            )
            for row in rows
        ]
        return CostBreakdown(items=items, total_cost_cents=sum(i.cost_cents for i in items))

    # ---- 内部 ----


def _month_end(anchor: date) -> date:
    return (anchor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
