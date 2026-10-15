"""仓库基类：强制显式 tenant_id + 会话上下文校验（ADR-003 查询层防护）。

铁律（SPEC §4.4 / 坑 4 / 坑 5）：
1. 所有租户表仓库方法签名必须带 tenant_id——编译期保障，不靠自觉
2. 执行前校验会话租户上下文已设置且匹配（fail-closed + 显式告警）
3. 「tenant 不匹配」与「不存在」抛同一个 NotFoundError，服务层不可区分
   （403 是资源枚举 oracle，坑 5）
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from app.core.errors import NotFoundError
from app.db.rls import ensure_tenant_context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository:
    """租户仓库基类。子类按资源一个文件，禁止跨模块直连对方仓库。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _guard(self, tenant_id: uuid.UUID) -> None:
        await ensure_tenant_context(self.session, tenant_id)

    async def _get_or_404(self, model: type[T], tenant_id: uuid.UUID, entity_id: uuid.UUID) -> T:
        """按主键取租户内实体。查不到（含跨租户被 RLS 过滤）统一 NotFound。"""
        await self._guard(tenant_id)
        stmt = select(model).where(
            model.id == entity_id,  # type: ignore[attr-defined]
            model.tenant_id == tenant_id,  # type: ignore[attr-defined]
        )
        result = await self.session.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            # 不区分「不存在」与「属于其他租户」——统一 404（SPEC §4.4 越权响应语义）
            raise NotFoundError()
        return entity

    async def _list(
        self, model: type[T], tenant_id: uuid.UUID, *, page: int, limit: int, order_by: Any
    ) -> tuple[list[T], int]:
        """分页列表。SQL 显式 WHERE tenant_id（RLS 之外的纵深防御 + 查询计划可见）。"""
        await self._guard(tenant_id)
        count_stmt = (
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        result = await self.session.execute(
            select(model)
            .where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
            .order_by(order_by)
            .limit(limit)
            .offset((page - 1) * limit)
        )
        return list(result.scalars().all()), total
