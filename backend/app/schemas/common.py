"""统一响应封装（SPEC §5.1：{code: 0, data, message: ""}）。

只放响应结构。错误码与业务异常在 app/core/errors.py（单一职责）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# API 处理器统一返回类型（信封 dict）
ApiResponse = dict[str, Any]


class Envelope(BaseModel):
    """成功响应信封。"""

    code: int = 0
    data: dict[str, Any] | None = None
    message: str = ""


class ErrorEnvelope(BaseModel):
    """错误响应信封。HTTP status 由 ErrorCode.http_status 决定。"""

    code: int
    data: dict[str, Any] | None = None
    message: str


class PagedList(BaseModel):
    """分页响应（SPEC §5.1：?page=1&limit=20&sort=-created_at）。"""

    items: list[Any]
    total: int
    page: int
    limit: int
    hasMore: bool


def ok(data: Any = None, message: str = "") -> ApiResponse:
    """组装成功响应体。data 为 None 时序列化为 null。"""
    return {"code": 0, "data": data, "message": message}


def paged(items: list[Any], total: int, page: int, limit: int) -> ApiResponse:
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "hasMore": page * limit < total,
    }
