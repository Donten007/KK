"""请求上下文中间件：X-Request-Id 贯穿 + 结构化访问日志 + 耗时。

AC-14 边界：访问日志只记元数据（方法/路径/状态码/耗时/请求 ID），
不记请求体与响应体（可能含 prompt 全文或客户业务内容）。
"""

from __future__ import annotations

import time
import uuid

from app.core.logging import get_logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = get_logger("http")

_REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 未捕获异常：记日志后交全局处理器（此处不吞）
            logger.exception(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
            )
            raise
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
