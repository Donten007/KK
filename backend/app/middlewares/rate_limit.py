"""速率限制（SPEC §4.5 安全清单：敏感端点 10 次/分钟；G2 抓取限流见 scraping 模块）。

实现：Redis 固定窗口计数（INCR + EXPIRE）。
降级：Redis 不可用时 fail-open 并记 WARNING——限流不可用不影响隔离与账务
（SPEC §10.7：Redis 故障只降级限流，不降级隔离）。

注意：限流键含调用方 IP。IP 只用于限流计数，**不进入任何埋点/日志持久化**
（TRACKING-GUARD 禁记项；「不采集 IP」是无例外承诺）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio
from app.core.errors import RateLimitedError
from app.core.logging import get_logger
from fastapi import Request

logger = get_logger("rate_limit")


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int


async def _redis_client() -> redis.asyncio.Redis:
    from app.config import get_settings

    return redis.asyncio.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
    )


async def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(policy: RateLimitPolicy) -> Callable[[Request], Awaitable[None]]:
    """生成限流依赖。计数键 = endpoint + IP（按端点独立计数，不共享窗口）。"""

    async def dependency(request: Request) -> None:
        from app.config import get_settings

        if not get_settings().rate_limit_enabled:
            return
        ip = await _client_ip(request)
        key = f"rate_limit:{request.url.path}:{ip}"
        try:
            client = await _redis_client()
            try:
                current = await client.incr(key)
                if current == 1:
                    await client.expire(key, policy.window_seconds)
                if current > policy.limit:
                    raise RateLimitedError()
            finally:
                await client.aclose()
        except RateLimitedError:
            raise
        except Exception as exc:  # Redis 故障 fail-open，绝不让限流拖垮业务
            logger.warning("rate_limit_redis_unavailable", tag="rate_limit_degraded", error=str(exc))

    return dependency
