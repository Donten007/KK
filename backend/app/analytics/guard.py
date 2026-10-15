"""埋点守门：写入前过滤（TRACKING-GUARD 防线 2/3/4）。

顺序（不可颠倒）：
1. 事件名白名单 —— 不在枚举内**整条丢弃**（schema 层 Literal 已挡一层，
   这里再挡一层防止 service 被内部调用绕过）
2. 属性白名单 —— 未知属性**丢弃该属性**（不是整条，否则一个多余字段
   会让整个事件丢失）
3. 黑名单 + 值长度 —— 命中黑名单或超长的属性**整条丢弃**
4. tenant_id 从 JWT 解析 —— 请求体传入的 tenant_id **一律忽略**

【需资深】为什么「写入前过滤」而不是「写入后清洗」：
清洗意味着内容已经进过我们的系统（可能进日志、进备份、进内存转储）。
TRACKING-GUARD 的本质是把隐私承诺从「人记得」变成「结构上不可能违反」。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.analytics.events import is_allowed_event
from app.analytics.property_models import (
    ALLOWED_VALUE_TYPES,
    BANNED_PROPERTY_KEYS,
    allowed_properties,
    value_limit_for,
)
from app.core.logging import get_logger

logger = get_logger("analytics")


@dataclass
class IngestResult:
    """上报结果。计数是「丢弃量必须可见」的载体（TRACKING-GUARD §四）。"""

    accepted: int = 0
    dropped: int = 0
    dropped_attributes: int = 0
    accepted_rows: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "accepted": self.accepted,
            "dropped": self.dropped,
            "dropped_attributes": self.dropped_attributes,
        }


def filter_event(
    *, event: str, properties: dict[str, Any], result: IngestResult
) -> dict[str, Any] | None:
    """单事件过滤。返回可入库属性；None 表示整条丢弃。"""
    # 防线 1：事件名白名单
    if not is_allowed_event(event):
        result.dropped += 1
        logger.warning("analytics_event_dropped", tag="analytics_dropped_event", event_name=event)
        return None

    # 防线 2：属性白名单（每事件独立）
    whitelist = allowed_properties(event)
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        if key.lower() in BANNED_PROPERTY_KEYS:
            # 防线 3：属性名黑名单 → 整条丢弃（不是只丢这个属性）
            result.dropped += 1
            logger.warning(
                "analytics_event_dropped",
                tag="analytics_dropped_banned_property",
                event_name=event,
                property_key=key,
            )
            return None
        if key not in whitelist:
            result.dropped_attributes += 1
            continue
        if not isinstance(value, ALLOWED_VALUE_TYPES):
            result.dropped_attributes += 1
            continue
        limit = value_limit_for(event)
        if isinstance(value, str) and len(value) > limit:
            # 防线 3 的核心：长度阈值。这条不依赖「猜对字段名」——
            # 属性名可以叫 context/body/whatever，内容类字段的共性是很长
            result.dropped += 1
            logger.warning(
                "analytics_event_dropped",
                tag="analytics_dropped_value_too_long",
                event_name=event,
                property_key=key,
                value_length=len(value),
            )
            return None
        cleaned[key] = value

    return cleaned


def build_rows(
    *,
    events: list[tuple[str, dict[str, Any]]],
    tenant_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> IngestResult:
    """批量过滤并组装待入库行。

    防线 4：tenant_id **只从 JWT 来**。请求体里即使带了 tenant_id 也被忽略
    （调用方根本拿不到它——见 schemas/analytics.py 的 extra='forbid'）。
    tenant_id 缺失 → 全部丢弃 + WARNING（不静默）。
    """
    result = IngestResult()
    if tenant_id is None:
        result.dropped += len(events)
        logger.warning(
            "analytics_no_tenant_context",
            tag="analytics_no_tenant_context",
            count=len(events),
        )
        return result

    for event, properties in events:
        cleaned = filter_event(event=event, properties=properties, result=result)
        if cleaned is None:
            continue
        result.accepted += 1
        result.accepted_rows.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "event": event,
                "properties": cleaned,
            }
        )
    return result