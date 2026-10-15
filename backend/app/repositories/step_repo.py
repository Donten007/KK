"""task_steps 仓库（L3 业务层）。

PRIMARY KEY (goal_id, step_ordinal) **就是幂等键**（ADR-011 / SPEC 坑 3）：
checkpoint 与业务数据不在同一事务，「业务成功但 checkpoint 未落盘」必然发生，
重放时必须靠幂等键去重，而不是靠"只执行一次"的假设。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.goal import TaskStep
from app.repositories.base import BaseRepository
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert


class TaskStepRepository(BaseRepository):
    async def upsert_running(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, ordinal: int, title: str
    ) -> TaskStep:
        """幂等写入 running 步。已存在则不覆盖终态（重放安全）。"""
        await self._guard(tenant_id)
        stmt = (
            pg_insert(TaskStep)
            .values(
                goal_id=goal_id,
                step_ordinal=ordinal,
                tenant_id=tenant_id,
                title=title,
                status="running",
                started_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["goal_id", "step_ordinal"])
        )
        await self.session.execute(stmt)
        await self.session.flush()
        row = await self.get(tenant_id=tenant_id, goal_id=goal_id, ordinal=ordinal)
        if row is None:  # 刚 UPSERT 必然存在；不存在说明数据被外部删除，属异常
            raise RuntimeError("task_step upsert 后读不到，请检查数据一致性")
        return row

    async def get(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, ordinal: int
    ) -> TaskStep | None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TaskStep).where(
                TaskStep.tenant_id == tenant_id,
                TaskStep.goal_id == goal_id,
                TaskStep.step_ordinal == ordinal,
            )
        )
        return result.scalar_one_or_none()

    async def finish(
        self,
        *,
        tenant_id: uuid.UUID,
        goal_id: uuid.UUID,
        ordinal: int,
        status: str,
        output_ref: str | None = None,
        cost_cents: int = 0,
        model_id: str | None = None,
        tool_name: str | None = None,
        tool_signature: str | None = None,
        delta_artifacts: int = 0,
        error_code: str | None = None,
    ) -> None:
        """完成一步。**成本只在 succeeded 时累加**——已完成部分不重复计费（AC-4）。"""
        await self._guard(tenant_id)
        await self.session.execute(
            update(TaskStep)
            .where(
                TaskStep.tenant_id == tenant_id,
                TaskStep.goal_id == goal_id,
                TaskStep.step_ordinal == ordinal,
            )
            .values(
                status=status,
                output_ref=output_ref,
                cost_cents=cost_cents,
                model_id=model_id,
                tool_name=tool_name,
                tool_signature=tool_signature,
                delta_artifacts=delta_artifacts,
                error_code=error_code,
                ended_at=datetime.now(UTC),
            )
        )

    async def list_for_goal(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID
    ) -> list[TaskStep]:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TaskStep)
            .where(TaskStep.tenant_id == tenant_id, TaskStep.goal_id == goal_id)
            .order_by(TaskStep.step_ordinal)
        )
        return list(result.scalars().all())

    async def succeeded_count(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> int:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(func.count())
            .select_from(TaskStep)
            .where(
                TaskStep.tenant_id == tenant_id,
                TaskStep.goal_id == goal_id,
                TaskStep.status == "succeeded",
            )
        )
        return int(result.scalar_one())


