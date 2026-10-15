"""用量服务：**两个口径走两条数据路径**（AC-14b / AC-C6 / ADR-017）。

owner 口径：只查 `usage_daily`（成本聚合表），**不 join usage_records 的 token 字段**。
        这是第二道防线——即使 controller 逻辑被改，owner 响应里也拿不到 token。
admin 口径：查 `usage_records`（含 token 明细）。

【需资深】禁止把两个口径写成一个函数再用参数切换——那样等于回到
「读了再剔除」，泄漏就退化成「每个人每次都记得剔除」。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.db.rls import tenant_transaction
from app.models.job import Agent
from app.models.usage import UsageDaily, UsageRecord
from app.repositories.base import BaseRepository
from app.schemas.usage import (
    AdminUsageByAgent,
    AdminUsageByModel,
    AdminUsageSummary,
    OwnerRoi,
    OwnerUsageDay,
    OwnerUsageItem,
    OwnerUsageSummary,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 订阅月费（分）。用于 ROI = (节省人力 - 订阅费) / 订阅费（SPEC §2.5 判据 3）
MONTHLY_SUBSCRIPTION_CENTS = 89900


class OwnerUsageRepository(BaseRepository):
    """owner 口径仓库。**只允许查 usage_daily**，方法名里出现 token 即违规。"""

    async def month_totals(
        self, *, tenant_id: uuid.UUID, start: date, end: date
    ) -> tuple[int, int]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(UsageDaily.cost_cents), 0),
                func.coalesce(func.sum(UsageDaily.task_count), 0),
            ).where(
                UsageDaily.tenant_id == tenant_id,
                UsageDaily.bucket_day >= start,
                UsageDaily.bucket_day <= end,
            )
        )
        cost, tasks = result.one()
        return int(cost), int(tasks)

    async def by_agent(
        self, *, tenant_id: uuid.UUID, start: date, end: date
    ) -> list[tuple[uuid.UUID, int, int]]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(
                UsageDaily.agent_id,
                func.sum(UsageDaily.cost_cents),
                func.sum(UsageDaily.task_count),
            )
            .where(
                UsageDaily.tenant_id == tenant_id,
                UsageDaily.bucket_day >= start,
                UsageDaily.bucket_day <= end,
            )
            .group_by(UsageDaily.agent_id)
        )
        return [(row[0], int(row[1] or 0), int(row[2] or 0)) for row in result.all()]

    async def by_day(
        self, *, tenant_id: uuid.UUID, start: date, end: date
    ) -> list[tuple[date, int]]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(UsageDaily.bucket_day, func.sum(UsageDaily.cost_cents))
            .where(
                UsageDaily.tenant_id == tenant_id,
                UsageDaily.bucket_day >= start,
                UsageDaily.bucket_day <= end,
            )
            .group_by(UsageDaily.bucket_day)
            .order_by(UsageDaily.bucket_day)
        )
        return [(row[0], int(row[1] or 0)) for row in result.all()]


class AdminUsageRepository(BaseRepository):
    """admin 口径仓库：读 usage_records 的 token 明细。"""

    async def by_model(
        self, *, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, str, int, int, int]]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(
                UsageRecord.provider,
                UsageRecord.model,
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
            )
            .where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.bucket_hour >= start,
                UsageRecord.bucket_hour < end,
            )
            .group_by(UsageRecord.provider, UsageRecord.model)
        )
        return [
            (r[0], r[1], int(r[2]), int(r[3]), int(r[4])) for r in result.all()
        ]

    async def by_agent(
        self, *, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[uuid.UUID | None, int, int, int]]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(
                UsageRecord.agent_id,
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
            )
            .where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.bucket_hour >= start,
                UsageRecord.bucket_hour < end,
            )
            .group_by(UsageRecord.agent_id)
        )
        return [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in result.all()]


class UsageService:
    """用量服务。两个口径方法签名不同、返回类型不同，不接受 role 参数切换。"""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.owner_repo = OwnerUsageRepository(session)
        self.admin_repo = AdminUsageRepository(session)

    async def owner_summary(self, *, period: str | None = None) -> OwnerUsageSummary:
        """owner 口径。数据源：usage_daily（成本聚合），**不读 token 表**。"""
        month_start, month_end = _month_range(period)
        async with tenant_transaction(self.session, self.tenant_id):
            total_cost, task_count = await self.owner_repo.month_totals(
                tenant_id=self.tenant_id, start=month_start, end=month_end
            )
            agent_rows = await self.owner_repo.by_agent(
                tenant_id=self.tenant_id, start=month_start, end=month_end
            )
            day_rows = await self.owner_repo.by_day(
                tenant_id=self.tenant_id, start=month_start, end=month_end
            )
            names = await self._agent_names([r[0] for r in agent_rows])
            hourly_rate = await self._hourly_rate()

        roi = await self._roi(
            task_count=task_count,
            hourly_rate_cny=hourly_rate,
            baseline_minutes=self.baseline_minutes,
        )
        return OwnerUsageSummary(
            period=f"{month_start:%Y-%m}",
            total_cost_cents=total_cost,
            total_task_count=task_count,
            cost_by_agent=[
                OwnerUsageItem(
                    agent_id=str(agent_id),
                    agent_name=names.get(agent_id, "未命名员工"),
                    task_count=tasks,
                    cost_cents=cost,
                )
                for agent_id, cost, tasks in agent_rows
            ],
            cost_by_day=[
                OwnerUsageDay(date=str(day), cost_cents=cost) for day, cost in day_rows
            ],
            roi=roi,
        )

    async def admin_summary(self, *, period: str | None = None) -> AdminUsageSummary:
        """admin 口径。数据源：usage_records（含 token 明细）。"""
        month_start, month_end = _month_range(period)
        start_dt = datetime.combine(month_start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(month_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        async with tenant_transaction(self.session, self.tenant_id):
            model_rows = await self.admin_repo.by_model(
                tenant_id=self.tenant_id, start=start_dt, end=end_dt
            )
            agent_rows = await self.admin_repo.by_agent(
                tenant_id=self.tenant_id, start=start_dt, end=end_dt
            )
        total_cost = sum(r[4] for r in model_rows)
        return AdminUsageSummary(
            period=f"{month_start:%Y-%m}",
            total_cost_cents=total_cost,
            usage_by_model=[
                AdminUsageByModel(
                    provider=provider,
                    model_id=model,
                    input_tokens=inp,
                    output_tokens=out,
                    task_count=0,
                    cost_cents=cost,
                )
                for provider, model, inp, out, cost in model_rows
            ],
            usage_by_agent=[
                AdminUsageByAgent(
                    agent_id=str(agent_id or "unassigned"),
                    input_tokens=inp,
                    output_tokens=out,
                    cost_cents=cost,
                )
                for agent_id, inp, out, cost in agent_rows
                if agent_id is not None
            ],
            budget_trigger_rate=0.0,
        )

    # ---- ROI 折算 ----

    baseline_minutes: float | None = None

    async def _hourly_rate(self) -> float | None:
        from app.models.tenant import Tenant

        result = await self.session.execute(
            select(Tenant.human_hourly_rate_cents).where(Tenant.id == self.tenant_id)
        )
        cents = result.scalar_one_or_none()
        if not cents:
            return None  # 未配置 → saved_hours 为 null（不返回 0）
        return round(cents / 100, 2)

    async def _roi(
        self, *, task_count: int, hourly_rate_cny: float | None, baseline_minutes: float | None
    ) -> OwnerRoi:
        """折算口径：(baseline_minutes_per_run × 本期运行次数) ÷ 60（openapi 定义）。

        未配置人工基线时返回 saved_hours=null，**不返回 0**——
        0 会被老板读成「没省时间」。
        """
        if not baseline_minutes or not hourly_rate_cny or task_count <= 0:
            return OwnerRoi(
                saved_hours=None,
                baseline_configured=False,
                baseline_minutes_per_run=baseline_minutes,
                hourly_rate_cny=hourly_rate_cny,
                roi_ratio=None,
            )
        saved_hours = round(baseline_minutes * task_count / 60, 2)
        saved_cents = saved_hours * hourly_rate_cny * 100
        roi_ratio = round((saved_cents - MONTHLY_SUBSCRIPTION_CENTS) / MONTHLY_SUBSCRIPTION_CENTS, 2)
        return OwnerRoi(
            saved_hours=saved_hours,
            baseline_configured=True,
            baseline_minutes_per_run=baseline_minutes,
            hourly_rate_cny=hourly_rate_cny,
            roi_ratio=roi_ratio,
        )

    async def _agent_names(self, agent_ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        if not agent_ids:
            return {}
        ids = [a for a in agent_ids if a is not None]
        if not ids:
            return {}
        result = await self.session.execute(
            select(Agent.id, Agent.name).where(
                Agent.tenant_id == self.tenant_id, Agent.id.in_(ids)
            )
        )
        return {row[0]: row[1] for row in result.all()}


def _month_range(period: str | None) -> tuple[date, date]:
    if period:
        year, _, month = period.partition("-")
        start = date(int(year), int(month), 1)
    else:
        today = datetime.now(UTC).date()
        start = today.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month - timedelta(days=1)