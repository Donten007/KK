"""task_artifacts / goal_events / goal_progress_state 仓库。

三者的共同点：都是「执行过程的旁路记录」，与 goal 主状态解耦——
goal 被删则级联删除，但它们不参与 goal 状态机的判定逻辑。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.goal import GoalEvent, GoalProgressState, TaskArtifact
from app.repositories.base import BaseRepository
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert


class TaskArtifactRepository(BaseRepository):
    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        goal_id: uuid.UUID,
        artifact_id: uuid.UUID,
        step_ordinal: int,
        kind: str,
        content_hash: str,
    ) -> bool:
        """登记产出物。幂等：同 (goal_id, artifact_id) 重复写入不报错。

        返回 True 表示这是**新内容**（S2 增量为 1），False 表示内容已存在
        （改了又改回原样 → S2 不计增量）。
        """
        await self._guard(tenant_id)
        existing = await self._find(tenant_id=tenant_id, goal_id=goal_id, artifact_id=artifact_id)
        stmt = (
            pg_insert(TaskArtifact)
            .values(
                goal_id=goal_id,
                artifact_id=artifact_id,
                tenant_id=tenant_id,
                step_ordinal=step_ordinal,
                kind=kind,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(index_elements=["goal_id", "artifact_id"])
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return existing is None or existing.content_hash != content_hash

    async def _find(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> TaskArtifact | None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(TaskArtifact).where(
                TaskArtifact.tenant_id == tenant_id,
                TaskArtifact.goal_id == goal_id,
                TaskArtifact.artifact_id == artifact_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_for_goal(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> int:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(func.count())
            .select_from(TaskArtifact)
            .where(TaskArtifact.tenant_id == tenant_id, TaskArtifact.goal_id == goal_id)
        )
        return int(result.scalar_one())


class GoalEventRepository(BaseRepository):
    async def append(
        self,
        *,
        tenant_id: uuid.UUID,
        goal_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        visibility: str = "admin",
    ) -> GoalEvent:
        """追加事件。seq 用 Redis INCR 分配（SPEC §4.9）；本骨架先取
        当前最大 seq + 1（单写入者场景），生产换 Redis 后无缝替换。"""
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(func.coalesce(func.max(GoalEvent.seq), 0)).where(
                GoalEvent.tenant_id == tenant_id, GoalEvent.goal_id == goal_id
            )
        )
        seq = int(result.scalar_one()) + 1
        row = GoalEvent(
            goal_id=goal_id,
            tenant_id=tenant_id,
            seq=seq,
            event_type=event_type,
            payload=payload,
            visibility=visibility,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_goal(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, role: str
    ) -> list[GoalEvent]:
        """按调用方角色在**服务端**过滤 visibility（ADR-017）。"""
        await self._guard(tenant_id)
        stmt = select(GoalEvent).where(
            GoalEvent.tenant_id == tenant_id, GoalEvent.goal_id == goal_id
        )
        if role != "admin":
            stmt = stmt.where(GoalEvent.visibility == "owner")
        result = await self.session.execute(stmt.order_by(GoalEvent.seq))
        return list(result.scalars().all())


class GoalProgressRepository(BaseRepository):
    async def load(self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> GoalProgressState | None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(GoalProgressState).where(
                GoalProgressState.tenant_id == tenant_id,
                GoalProgressState.goal_id == goal_id,
            )
        )
        return result.scalar_one_or_none()

    async def save(
        self, *, tenant_id: uuid.UUID, goal_id: uuid.UUID, state: dict[str, Any]
    ) -> GoalProgressState:
        """UPSERT 检测窗口状态。崩溃重启后从这里恢复，不归零。"""
        await self._guard(tenant_id)
        stmt = (
            pg_insert(GoalProgressState)
            .values(
                goal_id=goal_id,
                tenant_id=tenant_id,
                idle_streak=state["idle_streak"],
                recent_signatures=state["recent_signatures"],
                seen_tool_windows=state["seen_tool_windows"],
                identical_signature_streak=state["identical_signature_streak"],
                soft_pause_count=state["soft_pause_count"],
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=["goal_id"],
                set_={
                    "idle_streak": state["idle_streak"],
                    "recent_signatures": state["recent_signatures"],
                    "seen_tool_windows": state["seen_tool_windows"],
                    "identical_signature_streak": state["identical_signature_streak"],
                    "soft_pause_count": state["soft_pause_count"],
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
        loaded = await self.load(tenant_id=tenant_id, goal_id=goal_id)
        assert loaded is not None  # 刚 UPSERT 必然存在
        return loaded