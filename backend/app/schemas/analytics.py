"""埋点上报 schema（openapi `/api/v1/analytics/events`）。

防线 1 落在 `name: EventName`（Literal 联合类型）—— 不在枚举内 → Pydantic
直接 422，**非法事件根本进不了系统**。契约层同时声明 enum，前端
`openapi-typescript` 生成的类型天然受限，写错事件名在编译期就报错。

防线 4 落在这里：model_config extra='forbid' + 无 tenant_id 字段
—— 请求体**根本无法传 tenant_id**。
"""

from __future__ import annotations

from typing import Any

from app.analytics.events import EventName
from pydantic import BaseModel, ConfigDict, Field

MAX_EVENTS_PER_REQUEST = 20


class AnalyticsEventIn(BaseModel):
    """单条上报。properties 是裸 dict——白名单在写入前过滤时逐键判定
    （防线 2 要求「未知属性丢弃该属性」，不能用静态模型硬拒绝整条）。"""

    model_config = ConfigDict(extra="forbid")

    name: EventName
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None  # ISO8601，可选；不用于计算保留期


class AnalyticsBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[AnalyticsEventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_REQUEST)


class AnalyticsIngestOut(BaseModel):
    """上报结果。三个计数都是「丢弃量必须可见」的载体。"""

    accepted: int
    dropped: int
    dropped_attributes: int = 0