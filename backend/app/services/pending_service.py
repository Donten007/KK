"""待确认队列服务（/pending 页 + 「要你管」板块）。

resolve 的语义（「带修改恢复」是核心，不是纸面能力）：
- approve：标记 resolved + 恢复 goal（从 checkpoint 续跑，用原输入）
- amend：标记 resolved + 把新值写入 goal.input_payload + 恢复 goal（续跑时用新值）

【需资深】为什么 amend 必须把新值写进 goal.input_payload 而不是只存 pending：
executor 恢复时读的是 goal.input_payload——如果新值只躺在 pending 行里，
续跑读不到，就是「纸面恢复」。写入 goal 后，图从 checkpoint 继续、executor
重新读 input_payload 即拿到新值（能力等价于 LangGraph 的 Command(resume=...)）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import ValidationError
from app.db.rls import tenant_transaction
from app.models.goal import Goal
from app.repositories.pending_repo import PendingItemRepository, waiting_days
from app.services.goal_service import GoalService
from sqlalchemy import TextClause, text, update
from sqlalchemy.ext.asyncio import AsyncSession

VALID_RESOLVE_ACTIONS = ("approve", "amend")


class PendingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pending = PendingItemRepository(session)

    async def list(self, *, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        """待处理项列表。goal_title 由 join 提供，waiting_days 由 created_at 计算。"""
        async with tenant_transaction(self.session, tenant_id):
            rows = await self.pending.list_pending(tenant_id=tenant_id)
        return [
            {
                "id": str(item.id),
                "goal_id": str(item.goal_id) if item.goal_id else None,
                "agent_id": str(item.agent_id),
                "kind": item.kind,
                "goal_title": goal_title,
                "stopped_step": item.stopped_step,
                "waiting_days": waiting_days(item),
                "payload": item.payload,
                "created_at": item.created_at.isoformat(),
            }
            for item, goal_title in rows
        ]

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        pending_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        value: str | None,
    ) -> dict[str, Any]:
        """批准继续 / 带修改恢复。返回恢复后的 goal 状态。"""
        if action not in VALID_RESOLVE_ACTIONS:
            raise ValidationError("action 必须是 approve 或 amend")
        if action == "amend" and not value:
            raise ValidationError("amend 必须携带修改后的值")

        async with tenant_transaction(self.session, tenant_id):
            item = await self.pending.require(tenant_id=tenant_id, pending_id=pending_id)
            resolution = "approved" if action == "approve" else "amended"
            await self.pending.resolve(
                tenant_id=tenant_id,
                pending_id=pending_id,
                resolution=resolution,
                amended_value=value,
            )
            goal_id = item.goal_id
            amended_value = value

        # 事务提交后再触发恢复（避免恢复的 write 与 resolve 的 write 互相回滚）
        goal_service = GoalService(self.session, cancel_registry=None)
        if goal_id is not None:
            if action == "amend" and amended_value:
                await self._inject_amended_value(tenant_id, goal_id, amended_value)
            resume_result = await goal_service.resume(
                tenant_id=tenant_id, goal_id=goal_id, user_id=user_id
            )
        else:
            resume_result = {"goal_id": None, "status": "resolved_no_goal"}

        return {
            "pending_id": str(pending_id),
            "status": resume_result["status"],
            "resolution": resolution,
        }

    async def _inject_amended_value(
        self, tenant_id: uuid.UUID, goal_id: uuid.UUID, value: str
    ) -> None:
        """把修改后的值写进 goal.input_payload（续跑时 executor 读到新值）。"""
        async with tenant_transaction(self.session, tenant_id):
            await self.session.execute(
                update(Goal)
                .where(Goal.id == goal_id, Goal.tenant_id == tenant_id)
                .values(
                    input_payload=func_merge_input(Goal.input_payload, value)
                )
            )


def func_merge_input(current: Any, value: str) -> TextClause:
    """合并新值到 input_payload：amend 的值放进 amended_value 键，其余保留。"""
    del current
    return text("input_payload || jsonb_build_object('amended_value', :v)").bindparams(v=value)
