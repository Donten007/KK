"""埋点路由。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthUser, PlainSession
from app.controllers import analytics as controller
from app.schemas.analytics import AnalyticsBatchIn
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.post("/events", status_code=202)
async def ingest_events(
    body: AnalyticsBatchIn, user: AuthUser, session: PlainSession
) -> ApiResponse:
    return await controller.ingest(body, user, session)
