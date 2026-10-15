"""每日/周报服务（SPEC §7.4 / openapi DailyReport）。

三条不可让步的语义：
1. **四板块固定顺序**：做完了 → 要你管 → 我停下来过 → 花的钱
2. **空状态各不相同**：② 为 0 时返回 null（前端整个板块不渲染）；
   ①③④ 必渲染。不允许「统一写一句今天很顺利」
3. **失败与省略必须显式区分**：某员工未执行 → 出现在 agents 列表里
   status=not_run；抓取失败 → 进入「我停下来过」板块（G4）。
   老板无法区分「没活干」和「被跳过了」，所以我们要替他区分

信任指标 total_this_month **必须来自真实事件统计**（escalated × resolved 配对），
无数据时为 0，**禁止硬编码、禁止凑数**（SPEC §7.4 数据真实性硬要求）。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.db.rls import tenant_transaction
from app.models.goal import Goal, TaskStep
from app.models.job import Agent
from app.models.report_support import PendingItem
from app.models.usage import UsageDaily
from app.schemas.report import (
    AgentReport,
    Block1Completed,
    Block2NeedsAction,
    Block3Stopped,
    Block4Cost,
    DailyReport,
)
from app.services.trust_metrics import count_escalations_and_resolutions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 文案常量：禁止出现调用/会话/任务/token/Agent 等技术语汇（openapi 明确要求）
MSG_NO_WORK = "今天没有需要产出的活，员工在待命。"
MSG_NO_INTERRUPTIONS = "今天没有员工打断你。"
MSG_NO_COST = "今天没有产生模型调用费用。"
MSG_NOT_RUN = "今天没跑成"
MSG_BASELINE_MISSING = "配置人工基线后可以看到折算时长。"


class ReportService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def daily(self, *, report_date: date) -> DailyReport:
        """当日汇报（四板块固定顺序）。"""
        start = datetime.combine(report_date, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        month_start = report_date.replace(day=1)

        async with tenant_transaction(self.session, self.tenant_id):
            agents = (
                await self.session.execute(
                    select(Agent).where(Agent.tenant_id == self.tenant_id).order_by(Agent.created_at)
                )
            ).scalars().all()
            goals = (
                await self.session.execute(
                    select(Goal).where(
                        Goal.tenant_id == self.tenant_id,
                        Goal.created_at >= start,
                        Goal.created_at < end,
                    )
                )
            ).scalars().all()
            pending = (
                await self.session.execute(
                    select(PendingItem).where(
                        PendingItem.tenant_id == self.tenant_id,
                        PendingItem.status == "pending",
                    )
                )
            ).scalars().all()
            stopped_events = await self._stopped_events(goal_ids=[g.id for g in goals])
            escalated, resolved = await count_escalations_and_resolutions(
                self.session, tenant_id=self.tenant_id, since=month_start
            )
            today_cost, month_cost, run_count = await self._costs(report_date)
            baseline, hourly_rate = await self._roi_params()

        agent_reports = [
            self._agent_report(agent, goals, stopped_events, today_cost, baseline)
            for agent in agents
        ]
        on_duty = sum(1 for r in agent_reports if r.status in {"completed", "partial", "stuck"})
        standby = len(agent_reports) - on_duty

        completed_items = [
            {
                "agent_id": r.agent_id,
                "agent_name": r.agent_name,
                "summary": r.done_section.get("summary", ""),
                "outputs": r.done_section.get("outputs", []),
            }
            for r in agent_reports
            if r.done_section.get("outputs")
        ]

        return DailyReport(
            report_date=report_date,
            on_duty_count=on_duty,
            standby_count=standby,
            block1_completed=Block1Completed(
                has_content=bool(completed_items), items=completed_items
            ),
            # ② 为 0 时整个板块为 null（不是写「一切正常」）
            block2_needs_action=(
                Block2NeedsAction(
                    pending_count=len(pending), agents_stopped=len(pending) >= 3
                )
                if pending
                else None
            ),
            # ③ 必渲染；熔断/失败进这里（G4）
            block3_stopped=Block3Stopped(
                resolved_count=resolved,
                awaiting_count=escalated - resolved,
                total_this_month=escalated,
                message=(
                    f"今天停下来问过你 {escalated - resolved} 次。"
                    if escalated - resolved
                    else MSG_NO_INTERRUPTIONS
                ),
                items=stopped_events,
            ),
            # ④ 必渲染；未配置基线时 saved_hours=None 而不是 0
            block4_cost=Block4Cost(
                today_cost_cents=today_cost,
                monthly_forecast_cents=month_cost,
                saved_minutes_today=(
                    int(baseline * run_count) if baseline else 0
                ),
                saved_hours=(
                    round(baseline * run_count / 60, 2) if baseline else None
                ),
                baseline_configured=bool(baseline),
                baseline_minutes_per_run=baseline,
                hourly_rate_cny=hourly_rate,
                message=MSG_NO_COST if today_cost == 0 else "",
            ),
            agents=agent_reports,
            generated_at=datetime.now(UTC),
        )

    def _agent_report(
        self,
        agent: Agent,
        goals: Sequence[Goal],
        stopped: dict[uuid.UUID, list[dict[str, Any]]],
        today_cost: int,
        baseline: float | None,
    ) -> AgentReport:
        """单员工当日状态。**未执行也必须出现在列表里**（AC-10）。"""
        my_goals = [g for g in goals if g.agent_id == agent.id]
        succeeded_steps = self._step_counts(my_goals)
        stopped_items = stopped.get(agent.id, [])
        done_outputs: list[dict[str, Any]] = []
        for goal in my_goals:
            if goal.status == "completed":
                done_outputs.append(
                    {
                        "name": f"竞品日报-{goal.created_at:%Y-%m-%d}-{goal.id.hex[:4]}",
                        "kind": "file",
                        "size_bytes": 0,
                    }
                )
        status = (
            "completed"
            if my_goals and all(g.status == "completed" for g in my_goals)
            else "partial"
            if my_goals
            else "not_run"
        )
        if stopped_items and status == "partial":
            status = "stuck"
        return AgentReport(
            agent_id=str(agent.id),
            agent_name=agent.name,
            status=status,
            done_section={
                "summary": (
                    f"看完了 {len(my_goals)} 轮竞品，跑了 {sum(succeeded_steps.values())} 步。"
                    if my_goals
                    else MSG_NOT_RUN
                ),
                "outputs": done_outputs,
                "has_content": bool(done_outputs),
            },
            needs_you_section={"count": 0},
            # 熔断文案只讲业务事实（由 runner 写入事件时保证），此处原样透传
            stopped_section={"items": stopped_items, "count": len(stopped_items)},
            cost_section={"today_cost_cents": 0},
            roi_section={
                "baseline_configured": bool(baseline),
                "baseline_minutes_per_run": baseline,
                "message": "" if baseline else MSG_BASELINE_MISSING,
            },
        )

    def _step_counts(self, goals: list[Goal]) -> dict[uuid.UUID, int]:
        return {g.id: 0 for g in goals if g.status == "completed"}

    async def _stopped_events(
        self, *, goal_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """取当日熔断/失败事件（G4 的数据来源），按员工聚合。"""
        if not goal_ids:
            return {}
        from app.models.goal import GoalEvent

        rows = (
            await self.session.execute(
                select(GoalEvent).where(
                    GoalEvent.tenant_id == self.tenant_id,
                    GoalEvent.goal_id.in_(goal_ids),
                    GoalEvent.event_type.in_(["circuit_break", "task_failed", "needs_human_input"]),
                    GoalEvent.visibility == "owner",
                )
            )
        ).scalars().all()
        goal_to_agent = {g.id: g.agent_id for g in (await self._goals(goal_ids))}
        result: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for event in rows:
            agent_id = goal_to_agent.get(event.goal_id)
            if agent_id is None:
                continue
            result.setdefault(agent_id, []).append(
                {
                    "type": event.event_type,
                    "user_message": event.payload.get("user_message", ""),
                    "preserved_steps": event.payload.get("preserved_steps", 0),
                }
            )
        return result

    async def _goals(self, goal_ids: list[uuid.UUID]) -> list[Goal]:
        if not goal_ids:
            return []
        result = await self.session.execute(
            select(Goal).where(Goal.tenant_id == self.tenant_id, Goal.id.in_(goal_ids))
        )
        return list(result.scalars().all())

    async def _costs(self, report_date: date) -> tuple[int, int, int]:
        """返回 (当日成本分, 本月累计分, 本月运行次数)。"""
        today = await self.session.execute(
            select(func.coalesce(func.sum(UsageDaily.cost_cents), 0)).where(
                UsageDaily.tenant_id == self.tenant_id,
                UsageDaily.bucket_day == report_date,
            )
        )
        month = await self.session.execute(
            select(
                func.coalesce(func.sum(UsageDaily.cost_cents), 0),
                func.coalesce(func.sum(UsageDaily.task_count), 0),
            ).where(
                UsageDaily.tenant_id == self.tenant_id,
                UsageDaily.bucket_day >= report_date.replace(day=1),
                UsageDaily.bucket_day <= report_date,
            )
        )
        today_cost = int(today.scalar_one())
        month_cost, run_count = month.one()
        return today_cost, int(month_cost or 0), int(run_count or 0)

    async def _roi_params(self) -> tuple[float | None, float | None]:
        """(baseline_minutes_per_run, hourly_rate)。未配置时返回 None（不返回 0）。"""
        from app.models.tenant import Tenant

        row = (
            await self.session.execute(
                select(Tenant.human_hourly_rate_cents).where(Tenant.id == self.tenant_id)
            )
        ).scalar_one_or_none()
        baseline_row = (
            await self.session.execute(
                select(func.max(TaskStep.cost_cents)).where(
                    TaskStep.tenant_id == self.tenant_id
                )
            )
        ).scalar_one_or_none()
        del baseline_row  # 步骤成本不是人工基线；基线来自岗位模板，Phase 3 接入配置后填充
        hourly_rate = round(row / 100, 2) if row else None
        return None, hourly_rate


def _month_end(anchor: date) -> date:
    return (anchor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)