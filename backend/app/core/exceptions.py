"""全局异常处理器：BusinessError / RequestValidationError / 未捕获异常 → 统一信封。

安全约束：
- 未捕获异常对外只返回 5001 + 固定文案，细节只进日志（SPEC §5.4）
- 跨租户拒绝走 404 分支，响应体与「资源不存在」完全一致
- 错误日志异步化由中间件层保证不在请求路径同步写库（SPEC 坑 6）
"""

from __future__ import annotations

from app.core.errors import BusinessError, ErrorCode
from app.core.logging import get_logger
from app.schemas.common import ErrorEnvelope
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = get_logger("http")

_HTTP_TO_CODE = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    429: ErrorCode.RATE_LIMITED,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def _business_error(request: Request, exc: BusinessError) -> JSONResponse:
        if exc.code >= ErrorCode.INTERNAL_ERROR:
            logger.error("business_error_5xx", code=exc.code, message=exc.message)
        elif exc.code == ErrorCode.NOT_FOUND:
            # 跨租户拒绝审计（SPEC §4.4）：404 对「不存在」与「跨租户」不可区分，
            # 因此按 WARN 记录全部租户内 404（含跨租户尝试）。只记 ID 与租户对，
            # 不记目标资源标题/名称/文件名。
            user = getattr(request.state, "current_user", None)
            if user is not None:
                logger.warning(
                    "resource_access_denied",
                    tag="cross_tenant_denied",
                    tenant_id=str(user.tenant_id),
                    user_id=str(user.user_id),
                    path=request.url.path,
                )
        body = ErrorEnvelope(code=exc.code, message=exc.message, data=exc.data)
        headers = {"Retry-After": "60"} if exc.code == ErrorCode.RATE_LIMITED else None
        return JSONResponse(
            status_code=ErrorCode.http_status(exc.code), content=body.model_dump(), headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 不回显字段路径细节，统一 1001；细节在服务端日志（避免给攻击者输入结构反馈）
        logger.warning("request_validation_failed", errors=len(exc.errors()))
        body = ErrorEnvelope(code=ErrorCode.VALIDATION_FAILED, message=ErrorCode.default_message(ErrorCode.VALIDATION_FAILED))
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else ErrorCode.default_message(code)
        body = ErrorEnvelope(code=code, message=message)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        body = ErrorEnvelope(code=ErrorCode.INTERNAL_ERROR, message=ErrorCode.default_message(ErrorCode.INTERNAL_ERROR))
        return JSONResponse(status_code=500, content=body.model_dump())
