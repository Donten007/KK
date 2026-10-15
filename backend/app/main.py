"""入口：只做装配（挂中间件 + 挂路由 + 启动），零业务逻辑（code-organization 规则 4）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine
from app.middlewares.request_context import RequestContextMiddleware

logger = get_logger("main")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    logger.info("app_starting", env=settings.app_env)
    yield
    await dispose_engine()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="OPCAgentAI API",
        version="1.0.0",
        description="多租户 SaaS 平台 API（AI 员工，纯 BYOK）",
        lifespan=lifespan,
    )

    # 中间件（后注册的先执行）
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-Id", "Idempotency-Key"],
        max_age=86400,
    )

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
