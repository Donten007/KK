"""埋点控制器。

防线 1 在 schema 层（EventName Literal）已挡住非法事件名 → 422；
本控制器只负责把 (event, properties) 交给 service 做写入前过滤。
"""

from __future__ import annotations

from app.api.deps import AuthUser, PlainSession
from app.schemas.analytics import AnalyticsBatchIn
from app.schemas.common import ApiResponse, ok
from app.services.analytics_service import AnalyticsService


async def ingest(
    body: AnalyticsBatchIn, user: AuthUser, session: PlainSession
) -> ApiResponse:
    # tenant_id 来自 JWT，不从请求体取（body 里也没有该字段：extra='forbid'）
    result = await AnalyticsService(session).ingest(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        events=[(e.name, e.properties) for e in body.events],
    )
    return ok(result)
