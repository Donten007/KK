"""Goal 服务：创建 / 中止 / 续跑 / 查询。

中止语义（ADR-017 / 坑 10，本文件是唯一权威实现）：
    queued → running → stopping → cancelled
           └────────────→ completed  （中止生效前恰好跑完）
实现顺序**不可颠倒**：先置 stopping → 再发协作式取消信号 → 返回 200。
cancel **幂等**：重复调用返回同一状态不报错，且只发一次信号。

熔断计失败：circuit_break → goal.status=failed + error_code（不进 TCR 分子，
SPEC §2.5 归属规则）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.agents.cancellation import CancelRegistry, registry
from app.agents.estimators import GoalEstimate, estimate_goal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.rls import tenant_transaction, work_unit
from app.models.job import Agent, JobTemplate
from app.repositories.event_repo import GoalEventRepository, GoalProgressRepository
from app.repositories.goal_repo import GoalRepository
from app.repositories.step_repo import TaskStepRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("goal_service")

# ADR-017：stopping 最长 5 秒，超时由巡检器强制收敛为 cancelled
STOPPING_TIMEOUT_SECONDS = 5


class GoalService:
    def __init__(
        self, session: AsyncSession, *, cancel_registry: CancelRegistry | None = None
    ) -> None:
        self.session = session
        # 可注入：测试用独立 registry，生产用进程单例。默认取全局，
        # 保证「API 进程与 runner 同进程」时信号可达。
        self.cancel_registry = cancel_registry or registry
        self.goals = GoalRepository(session)
        self.steps = TaskStepRepository(session)
        self.events = GoalEventRepository(session)
        self.progress = GoalProgressRepository(session)

    # ---- 创建 ----

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str,
        input_payload: dict[str, Any],
    ) -> tuple[uuid.UUID, GoalEstimate]:
        """创建 goal 并返回预估。校验链：成员权限 → 员工存在 → 岗位模板。"""
        async with work_unit(self.session):
            agent = await self._get_agent(tenant_id, agent_id)
            template = await self._get_template(agent.job_template_id)
            urls = input_payload.get("urls") or []
            if urls and not all(isinstance(u, str) for u in urls):
                raise ValidationError("urls 必须是字符串列表")
            estimate = estimate_goal(template, url_count=len(urls))
            goal = await self.goals.create(
                tenant_id=tenant_id,
                agent_id=agent_id,
                created_by=user_id,
                title=title[:200],
                input_payload=input_payload,
                job_template_id=str(template.id),
                estimated_steps=estimate.steps,
                estimated_cost_cents=estimate.cost_cents,
                budget_cents=agent.monthly_budget_cents,
            )
            await self.progress.save(
                tenant_id=tenant_id,
                goal_id=goal.id,
                state={"idle_streak": 0, "recent_signatures": [],
                       "seen_tool_windows": [], "identical_signature_streak": 0,
                       "soft_pause_count": 0},
            )
            await self.events.append(
                tenant_id=tenant_id,
                goal_id=goal.id,
                event_type="task_queued",
                payload={"estimated_steps": estimate.steps},
                visibility="owner",
            )
            return goal.id, estimate

    # ---- 中止（幂等 + 先置 stopping）----

    async def cancel(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, Any]:
        """中止：先置 stopping → 再发信号 → 返回。顺序不可颠倒。"""
        async with tenant_transaction(self.session, tenant_id):
            goal = await self.goals.get(tenant_id=tenant_id, goal_id=goal_id)
            status = goal.status

            # 幂等 1：已完成/已取消/已失败 → 直接返回同一状态，不报错
            if status in {"completed", "cancelled", "failed", "expired"}:
                return {
                    "goal_id": str(goal_id),
                    "status": status,
                    "preserved_steps": await self.steps.succeeded_count(
                        tenant_id=tenant_id, goal_id=goal_id
                    ),
                }

            # 幂等 2：queued → 零延迟 cancelled（无需等 worker）
            if status == "pending":
                await self.goals.update_status(
                    tenant_id=tenant_id, goal_id=goal_id, status="cancelled",
                    ended_at=datetime.now(UTC),
                )
                await self.events.append(
                    tenant_id=tenant_id, goal_id=goal_id, event_type="task_cancelled",
                    payload={"preserved_steps": 0}, visibility="owner",
                )
                return {"goal_id": str(goal_id), "status": "cancelled", "preserved_steps": 0}

            # running / waiting_approval / stopping → 置 stopping（重复调用只置一次）
            if status == "stopping":
                preserved = await self.steps.succeeded_count(
                    tenant_id=tenant_id, goal_id=goal_id
                )
                return {"goal_id": str(goal_id), "status": "stopping", "preserved_steps": preserved}

            await self.goals.update_status(
                tenant_id=tenant_id, goal_id=goal_id, status="stopping"
            )

        # 事务提交后才发信号：worker 若立刻读库能看到 stopping（顺序要求）
        await self.cancel_registry.request_cancel(goal_id)
        logger.info("goal_cancel_requested", goal_id=str(goal_id), user_id=str(user_id))

        async with tenant_transaction(self.session, tenant_id):
            preserved = await self.steps.succeeded_count(tenant_id=tenant_id, goal_id=goal_id)
        return {"goal_id": str(goal_id), "status": "stopping", "preserved_steps": preserved}

    # ---- 续跑 ----

    async def resume(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, Any]:
        """断点续跑：校验状态 → resumed_count+1 → 交回 runner（checkpoint 决定从哪步继续）。"""
        async with tenant_transaction(self.session, tenant_id):
            goal = await self.goals.get(tenant_id=tenant_id, goal_id=goal_id)
            if goal.status == "completed":
                raise ConflictError("任务已完成，无需续跑")
            if goal.status == "stopping":
                raise ConflictError("任务正在中止，请稍后再试")
            if goal.status == "running":
                raise ConflictError("任务正在执行中")
            await self.goals.bump_resumed(tenant_id=tenant_id, goal_id=goal_id)
            await self.goals.update_status(tenant_id=tenant_id, goal_id=goal_id, status="pending")
            await self.events.append(
                tenant_id=tenant_id, goal_id=goal_id, event_type="task_resumed",
                payload={"resumed_count": goal.resumed_count + 1}, visibility="owner",
            )
            return {"goal_id": str(goal_id), "status": "pending"}

    # ---- 查询 ----

    async def get_detail(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, role: str
    ) -> dict[str, Any]:
        async with tenant_transaction(self.session, tenant_id):
            goal = await self.goals.get(tenant_id=tenant_id, goal_id=goal_id)
            step_rows = await self.steps.list_for_goal(tenant_id=tenant_id, goal_id=goal_id)
            data = {
                "id": str(goal.id),
                "agent_id": str(goal.agent_id),
                "status": goal.status,
                "title": goal.title,
                "estimated_steps": goal.estimated_steps,
                "actual_steps": len(step_rows),
                "estimated_cost_cents": goal.estimated_cost_cents,
                "actual_cost_cents": goal.spent_cents,
                "created_at": goal.created_at.isoformat(),
                "resumed_count": goal.resumed_count,
                "circuit_break_count": goal.circuit_break_count,
                "input": goal.title,
                "error_code": goal.error_code,
            }
        del role
        return data

    async def list_steps(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> list[dict[str, Any]]:
        async with tenant_transaction(self.session, tenant_id):
            await self.goals.get(tenant_id=tenant_id, goal_id=goal_id)  # 存在性 + 越权 404
            rows = await self.steps.list_for_goal(tenant_id=tenant_id, goal_id=goal_id)
        return [
            {
                "step_ordinal": r.step_ordinal,
                "title": r.title,
                "status": r.status,
                "cost_cents": r.cost_cents,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "error_code": r.error_code,
            }
            for r in rows
        ]

    async def list_events(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, role: str
    ) -> list[dict[str, Any]]:
        """按角色在服务端过滤 visibility（ADR-017）：owner 收不到 admin 级事件。"""
        async with tenant_transaction(self.session, tenant_id):
            await self.goals.get(tenant_id=tenant_id, goal_id=goal_id)
            rows = await self.events.list_for_goal(
                tenant_id=tenant_id, goal_id=goal_id, role=role
            )
        return [
            {
                "seq": r.seq,
                "event_type": r.event_type,
                "visibility": r.visibility,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    async def list_goals(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        limit: int,
        status: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        async with tenant_transaction(self.session, tenant_id):
            rows, total = await self.goals.list_for_tenant(
                tenant_id=tenant_id, page=page, limit=limit, status=status
            )
        return (
            [
                {
                    "id": str(r.id),
                    "agent_id": str(r.agent_id),
                    "status": r.status,
                    "title": r.title,
                    "estimated_steps": r.estimated_steps,
                    "estimated_cost_cents": r.estimated_cost_cents,
                    "actual_cost_cents": r.spent_cents,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
            total,
        )

    # ---- 内部 ----

    async def _get_agent(self, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        from sqlalchemy import select

        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:  # 跨租户与不存在不可区分（坑 5）
            raise NotFoundError("AI 员工不存在")
        return agent

    async def _get_template(self, template_id: uuid.UUID) -> JobTemplate:
        from sqlalchemy import select

        result = await self.session.execute(
            select(JobTemplate).where(JobTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise NotFoundError("岗位模板不存在")
        return template