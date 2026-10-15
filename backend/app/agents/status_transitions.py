"""Goal 状态收敛（每个终态一个函数，独立可测）。

为什么单独成文件：状态收敛是 F6-lite 最容易被改坏的部分（每个终态都要
同时更新 status + error_code + 事件 + 审计），与「图执行编排」混在一个文件里
会互相干扰。拆分后 runner 只负责流程，状态语义集中在这里。

铁律（ADR-017 / ADR-018）：
- circuit_break → status=failed（**熔断一律计失败**，不进 TCR 分子）
- 文案只讲业务事实，error_code 只留在 admin 侧（AC-F3）
- 已完成步骤保持原样，不回滚不置灰且不扣费
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.repositories.event_repo import GoalEventRepository
from app.repositories.goal_repo import GoalRepository
from app.repositories.pending_repo import PendingItemRepository
from app.repositories.step_repo import TaskStepRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("goal_status")

# 每租户同时处于 waiting_approval 的任务上限（soft pause DoS 防护）。
# 超限后软暂停转为熔断。数值未实测 —— Phase 3 按真实岗位并发量校准。
SOFT_PAUSE_TENANT_LIMIT = 5


class StatusTransitions:
    """状态收敛器。持有会话与租户，事务边界由调用方（work_unit）管理。"""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def set_running(self, goal_id: uuid.UUID) -> None:
        await self._update(goal_id, status="running")
        await self._event(goal_id, "task_started", {}, visibility="owner")

    async def set_completed(self, goal_id: uuid.UUID) -> None:
        await self._update(goal_id, status="completed", ended=True)
        await self._event(goal_id, "task_completed", {}, visibility="owner")

    async def set_failed(self, goal_id: uuid.UUID, error_code: str) -> None:
        await self._update(goal_id, status="failed", error_code=error_code, ended=True)
        await self._event(goal_id, "task_failed", {"error_code": error_code})

    async def set_cancelled(self, goal_id: uuid.UUID) -> None:
        await self._update(goal_id, status="cancelled", ended=True)
        preserved = await self._preserved(goal_id)
        await self._event(
            goal_id, "task_cancelled", {"preserved_steps": preserved}, visibility="owner"
        )

    async def set_circuit_break(
        self, goal_id: uuid.UUID, *, reason: str, user_message: str
    ) -> None:
        """熔断：计失败 + 保留成果 + 内联在任务行（不进待确认队列，ADR-018）。"""
        await GoalRepository(self.session).bump_circuit_break(
            tenant_id=self.tenant_id, goal_id=goal_id
        )
        await self._update(goal_id, status="failed", error_code=reason, ended=True)
        await self._event(
            goal_id,
            "circuit_break",
            {
                "user_message": user_message,
                "error_code": reason,
                "preserved_steps": await self._preserved(goal_id),
            },
            visibility="owner",
        )

    async def set_soft_pause(
        self,
        goal_id: uuid.UUID,
        user_message: str,
        *,
        step_title: str = "",
        step_ordinal: int = 0,
    ) -> None:
        """软阈值暂停（HITL）。

        【需资深】租户级上限：同一租户同时处于 waiting_approval 的任务超过
        SOFT_PAUSE_TENANT_LIMIT 时，不再新增暂停而是转为熔断 —— 无上限的
        暂停会占住队列且永不超时（DoS 面）。熔断文案只讲业务事实（AC-F3）。
        """
        repo = GoalRepository(self.session)
        waiting = await repo.count_by_status(tenant_id=self.tenant_id, status="waiting_approval")
        if waiting >= SOFT_PAUSE_TENANT_LIMIT:
            await self.set_circuit_break(
                goal_id,
                reason="soft_pause_limit",
                user_message="待确认的事情积压太多，我先停在这里。你处理完手头的，我再重新开始剩下的。",
            )
            return
        await self._update(goal_id, status="waiting_approval")
        await self._event(
            goal_id, "needs_human_input", {"user_message": user_message}, visibility="owner"
        )
        # 写入待确认队列（「要你管」板块的数据源）。
        # kind 恒为 needs_human_input：熔断不进队列（ADR-018）。
        goal = await repo.get(tenant_id=self.tenant_id, goal_id=goal_id)
        await PendingItemRepository(self.session).create(
            tenant_id=self.tenant_id,
            goal_id=goal_id,
            agent_id=goal.agent_id,
            payload={"user_message": user_message},
            evidence_ref=[],
            stopped_step=(step_title or None),
        )

    async def _update(
        self,
        goal_id: uuid.UUID,
        *,
        status: str,
        error_code: str | None = None,
        ended: bool = False,
    ) -> None:
        await GoalRepository(self.session).update_status(
            tenant_id=self.tenant_id,
            goal_id=goal_id,
            status=status,
            error_code=error_code,
            ended_at=datetime.now(UTC) if ended else None,
        )

    async def _preserved(self, goal_id: uuid.UUID) -> int:
        return await TaskStepRepository(self.session).succeeded_count(
            tenant_id=self.tenant_id, goal_id=goal_id
        )

    async def _event(
        self,
        goal_id: uuid.UUID,
        event_type: str,
        payload: dict[str, object],
        *,
        visibility: str = "admin",
    ) -> None:
        await GoalEventRepository(self.session).append(
            tenant_id=self.tenant_id,
            goal_id=goal_id,
            event_type=event_type,
            payload=payload,
            visibility=visibility,
        )
