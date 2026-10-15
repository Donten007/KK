"""单元测试：错误码表与信封（SPEC §5.4）。

跨租户 404 语义是阻断级约束：1003 只允许出现在租户内权限不足场景。
"""

from __future__ import annotations

from app.core.errors import (
    BusinessError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from app.core.exceptions import register_exception_handlers
from app.schemas.common import ok, paged
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_error_code_http_mapping() -> None:
    assert ErrorCode.http_status(ErrorCode.VALIDATION_FAILED) == 400
    assert ErrorCode.http_status(ErrorCode.UNAUTHENTICATED) == 401
    assert ErrorCode.http_status(ErrorCode.FORBIDDEN) == 403
    assert ErrorCode.http_status(ErrorCode.NOT_FOUND) == 404
    assert ErrorCode.http_status(ErrorCode.RATE_LIMITED) == 429
    assert ErrorCode.http_status(ErrorCode.INTERNAL_ERROR) == 500


def test_not_found_and_forbidden_are_distinct_codes() -> None:
    """1004 跨租户/不存在；1003 仅租户内。两者绝不可混用。"""
    assert NotFoundError().code == ErrorCode.NOT_FOUND
    assert ForbiddenError().code == ErrorCode.FORBIDDEN


def test_rate_limited_has_retry_after_header() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def _boom() -> None:
        raise RateLimitedError()

    with TestClient(app) as client:
        resp = client.get("/boom")
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"
    body = resp.json()
    assert body["code"] == ErrorCode.RATE_LIMITED
    assert body["message"]


def test_business_error_envelope_shape() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/conflict")
    async def _conflict() -> None:
        raise BusinessError(ErrorCode.CONFLICT, "该邮箱已注册，请直接登录")

    with TestClient(app) as client:
        resp = client.get("/conflict")
    assert resp.status_code == 409
    body = resp.json()
    assert set(body.keys()) == {"code", "data", "message"}
    assert body["code"] == 1005


def test_unhandled_exception_hides_details() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/crash")
    async def _crash() -> None:
        raise RuntimeError("secret internal detail: connection string postgresql://...")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/crash")
    assert resp.status_code == 500
    assert resp.json()["code"] == 5001
    assert "secret internal detail" not in resp.text


def test_ok_and_paged_envelope() -> None:
    body = ok({"a": 1})
    assert body == {"code": 0, "data": {"a": 1}, "message": ""}
    page = paged([1, 2], 5, 1, 2)
    assert page["hasMore"] is True
    assert paged([1, 2], 2, 1, 2)["hasMore"] is False
