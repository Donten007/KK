"""pending_items 仓库（RLS 保护）。

「要你管」板块 / /pending 页的数据源。goal_title 与 waiting_days 由查询时
join/computed 提供（不落列，避免与 goals 双写漂移）；stopped_step 落列
（软暂停那一刻的业务步骤标题，事后无法反推）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.goal import Goal
from app.models.job import Agent
from app.models.report_support import PendingItem
from app.repositories.base import BaseRepository
from sqlalchemy import func, select


class PendingItemRepository(BaseRepository):
    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        goal_id: uuid.UUID | None,
        agent_id: uuid.UUID,
        payload: dict[str, Any],
        evidence_ref: list[dict[str, Any]],
        stopped_step: str | None,
        kind: str = "needs_human_input",
    ) -> PendingItem:
        """新增待确认项。kind 只允许 needs_human_input（熔断不进队列，ADR-018）。"""
        await self._guard(tenant_id)
        row = PendingItem(
            tenant_id=tenant_id,
            goal_id=goal_id,
            agent_id=agent_id,
            kind=kind,
            payload=payload,
            evidence_ref=evidence_ref,
            stopped_step=stopped_step,
            status="pending",
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, *, tenant_id: uuid.UUID, pending_id: uuid.UUID) -> PendingItem | None:
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(PendingItem).where(
                PendingItem.tenant_id == tenant_id, PendingItem.id == pending_id
            )
        )
        return result.scalar_one_or_none()

    async def require(self, *, tenant_id: uuid.UUID, pending_id: uuid.UUID) -> PendingItem:
        """跨租户与不存在抛同一个 NotFound（坑 5，不区分）。"""
        from app.core.errors import NotFoundError

        row = await self.get(tenant_id=tenant_id, pending_id=pending_id)
        if row is None:
            raise NotFoundError()
        return row

    async def list_pending(
        self, *, tenant_id: uuid.UUID
    ) -> list[tuple[PendingItem, str | None]]:
        """待处理项 + 关联任务名（goal_title）。只返回 status=pending。"""
        await self._guard(tenant_id)
        result = await self.session.execute(
            select(PendingItem, Goal.title)
            .outerjoin(Goal, Goal.id == PendingItem.goal_id)
            .where(PendingItem.tenant_id == tenant_id, PendingItem.status == "pending")
            .order_by(PendingItem.created_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        pending_id: uuid.UUID,
        resolution: str,
        amended_value: str | None = None,
    ) -> PendingItem:
        """标记已处理。resolution ∈ {approved, amended}；amended 时把新值存进 payload。"""
        row = await self.require(tenant_id=tenant_id, pending_id=pending_id)
        if row.status != "pending":
            from app.core.errors import ConflictError

            raise ConflictError("该待确认项已处理")
        payload = dict(row.payload or {})
        payload["resolution"] = resolution
        if amended_value is not None:
            payload["amended_value"] = amended_value
        row.payload = payload
        row.status = "resolved"
        row.resolved_at = datetime.now(UTC)
        await self.session.flush()
        return row


def waiting_days(item: PendingItem, *, today: datetime | None = None) -> int:
    """已等待天数（升级信号，前端按它降序排「等最久在前」）。"""
    base = today or datetime.now(UTC)
    return max(0, (base.date() - item.created_at.date()).days)


__all__ = ["Agent", "PendingItemRepository", "func", "select", "waiting_days"]