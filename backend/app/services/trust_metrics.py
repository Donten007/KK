"""信任指标统计（日报与周报共用，**口径必须一致**）。

数据来源：goal_events 的真实事件配对计数
  escalated = task_escalated_to_human 事件数（对应 needs_human_input）
  resolved  = escalation_resolved 事件数

**禁止硬编码、禁止取整凑数、禁止在无数据时编造**（SPEC §7.4 数据真实性硬要求）——
硬编码或编造视为 P0 缺陷：信任指标造假等于在信任指标里投毒。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.models.goal import GoalEvent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def count_escalations_and_resolutions(
    session: AsyncSession, *, tenant_id: uuid.UUID, since: date
) -> tuple[int, int]:
    """返回 (escalated, resolved)。无数据时返回 0，**不返回估算值**。"""
    start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)

    async def _count(event_type: str) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(GoalEvent)
            .where(
                GoalEvent.tenant_id == tenant_id,
                GoalEvent.event_type == event_type,
                GoalEvent.created_at >= start,
            )
        )
        return int(result.scalar_one())

    escalated = await _count("needs_human_input")
    resolved = await _count("escalation_resolved")
    return escalated, resolved
