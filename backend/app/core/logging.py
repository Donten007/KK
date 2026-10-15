"""结构化日志（structlog）。

AC-14 边界：允许记录模型名、token 数、延迟、费用、工具名、参数摘要；
禁止记录 prompt 全文、工具返回全文、文档内容、检索到的 chunk 原文。
日志配置层通过 redaction 处理器把高危字段名统一打码，防止上游误传。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from app.config import get_settings

# AC-14：这些键的值永不进日志（prompt 全文 / 工具返回 / 文档内容 / 密钥）
_REDACT_KEYS = frozenset(
    {
        "prompt",
        "completion",
        "content",
        "document",
        "chunk_text",
        "api_key",
        "password",
        "token",
        "secret",
        "ciphertext",
        "authorization",
    }
)


def _redact_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # 让标准库日志（uvicorn / sqlalchemy）也走同一级别，避免双轨
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    # structlog.get_logger 返回 Any（动态代理），显式断言类型让 strict mypy 满意
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
