"""audit_logs 仓库（RLS 保护，append-only：只插不查改删）。"""

from __future__ import annotations

import uuid
from typing import Any

from app.models.audit import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository):
    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        level: str = "info",
        actor_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        result: str = "success",
        detail: dict[str, Any] | None = None,
    ) -> AuditLog:
        await self._guard(tenant_id)
        row = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            level=level,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            detail=detail,
        )
        self.session.add(row)
        await self.session.flush()
        return row
