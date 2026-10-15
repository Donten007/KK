"""goals / task_steps / task_artifacts / goal_events / goal_progress_state 仓库。

全部租户表，逐方法带 tenant_id 并触发上下文校验（ADR-003 查询层防护）。

幂等要点（SPEC 坑 3）：
- task_steps 用 PRIMARY KEY (goal_id, step_ordinal) + ON CONFLICT DO NOTHING
- task_artifacts 同理，(goal_id, artifact_id) 天然幂等
- 业务写入成功但 checkpoint 未落盘时，重放不会产生重复行
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.goal import (
    Goal,
)
from app.repositories.base import BaseRepository
from sqlalchemy import func, select, update


class GoalRepository(BaseRepository):
    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        created_by: uuid.UUID,
        title: str,
        input_payload: dict[str, Any],
        job_template_id: str | None,
        estimated_steps: int,
        estimated_cost_cents: int,
        budget_cents: int,
        goal_id: uuid.UUID | None = None,
    ) -> Goal:
        await self._guard(tenant_id)
        goal = Goal(
            id=goal_id or uuid.uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            created_by=created_by,
            title=title,
            input_payload=input_payload,
            job_template_id=job_template_id,
            estimated_steps=estimated_steps,
            estimated_cost_cents=estimated_cost_cents,
            budget_cents=budget_cents,
            status="pending",
        )
        self.session.add(goal)
        await self.session.flush()
        return goal

    async def get(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> Goal:
        return await self._get_or_404(Goal, tenant_id, goal_id)

    async def list_for_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[Goal], int]:
        await self._guard(tenant_id)
        stmt = select(Goal).where(Goal.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(Goal).where(Goal.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Goal.status == status)
            count_stmt = count_stmt.where(Goal.status == status)
        total = (await self.session.execute(count_stmt)).scalar_one()
        result = await self.session.execute(
            stmt.order_by(Goal.created_at.desc()).limit(limit).offset((page - 1) * limit)
        )
        return list(result.scalars().all()), total

    async def update_status(
        self,
        *,
        tenant_id: uuid.UUID,
        goal_id: uuid.UUID,
        status: str,
        error_code: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        await self._guard(tenant_id)
        values: dict[str, Any] = {"status": status}
        if error_code is not None:
            values["error_code"] = error_code
        if ended_at is not None:
            values["ended_at"] = ended_at
        if status == "stopping":
            values["stopping_since"] = datetime.now(UTC)
        elif status == "running":
            values["stopping_since"] = None
        await self.session.execute(
            update(Goal).where(Goal.id == goal_id, Goal.tenant_id == tenant_id).values(**values)
        )

    async def add_spent(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, cost_cents: int) -> None:
        await self._guard(tenant_id)
        await self.session.execute(
            update(Goal)
            .where(Goal.id == goal_id, Goal.tenant_id == tenant_id)
            .values(spent_cents=Goal.spent_cents + cost_cents)
        )

    async def bump_resumed(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> None:
        await self._guard(tenant_id)
        await self.session.execute(
            update(Goal)
            .where(Goal.id == goal_id, Goal.tenant_id == tenant_id)
            .values(resumed_count=Goal.resumed_count + 1)
        )

    async def bump_circuit_break(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> None:
        await self._guard(tenant_id)
        await self.session.execute(
            update(Goal)
            .where(Goal.id == goal_id, Goal.tenant_id == tenant_id)
            .values(circuit_break_count=Goal.circuit_break_count + 1)
        )

    async def count_stopping_older_than(self, *, tenant_id: uuid.UUID, seconds: int) -> list[Goal]:
        """巡检用：stopping 超过 N 秒未收敛的 goal（ADR-017 5 秒兜底）。"""
        await self._guard(tenant_id)
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
        result = await self.session.execute(
            select(Goal).where(
                Goal.tenant_id == tenant_id,
                Goal.status == "stopping",
                Goal.stopping_since.is_not(None),
                Goal.stopping_since < cutoff,
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self, *, tenant_id: uuid.UUID, status: str) -> int:
        """统计租户下处于某状态的 goal 数（soft pause 租户级上限用）。"""
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(func.count())
            .select_from(Goal)
            .where(Goal.tenant_id == tenant_id, Goal.status == status)
        )
        return int(result.scalar_one())


