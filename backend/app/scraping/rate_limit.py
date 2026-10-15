"""G2：频率限制（SPEC §4.5 / AC-B4）——**服务端强制，不靠 Agent 自觉**。

三层限流（SPEC §4.5 硬性指标）：
| 维度 | 上限 | 理由 |
|------|------|------|
| 单域名 | ≥2s 间隔 | 不压垮目标站 |
| 单租户 | ≤20 请求/分钟 | 单客户不能占满配额 |
| 全平台 | ≤200 请求/分钟 | 保护平台出网 IP |

【需资深】为什么必须服务端强制：LLM 会因重试高频请求，ADR-010 明确
「不能靠 Agent 自觉」。这三层都在**发起请求之前**判定，被拒时不产生任何
出网流量。

实现：进程内滑动窗口 + 锁。MVP 规模（100 租户 / 200 并发 Goal）下够用；
多 worker 部署时每 worker 各持一份，实际生效值是上限 × worker 数——
Phase 3 换 Redis 令牌桶（接口已抽象为 GuardLimiter，换实现不影响调用方）。
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from app.core.logging import get_logger

logger = get_logger("scraping.ratelimit")

DOMAIN_MIN_INTERVAL_SECONDS = 2.0
TENANT_RPM = 20
GLOBAL_RPM = 200

# 滑动窗口长度（秒）
_WINDOW_SECONDS = 60.0
# 单域名 last_request 保留时长：超过这个时间不再需要记（窗口已过）
_DOMAIN_RETENTION_SECONDS = 300.0


class RateLimited(Exception):
    """触发 G2 限流。调用方必须显式报告该失败（G4），不得静默重试。"""

    def __init__(self, scope: str, retry_after: float) -> None:
        self.scope = scope  # domain / tenant / global
        self.retry_after = retry_after
        super().__init__(f"rate limited: {scope}")


class GuardLimiter:
    """三层限流器。判定顺序：domain → tenant → global（从具体到宽泛）。"""

    def __init__(
        self,
        *,
        domain_interval: float = DOMAIN_MIN_INTERVAL_SECONDS,
        tenant_rpm: int = TENANT_RPM,
        global_rpm: int = GLOBAL_RPM,
    ) -> None:
        self._domain_interval = domain_interval
        self._tenant_rpm = tenant_rpm
        self._global_rpm = global_rpm
        self._last_request: dict[str, float] = {}
        self._tenant_hits: dict[str, deque[float]] = defaultdict(deque)
        self._global_hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, *, domain: str, tenant_id: str) -> None:
        """申请一次出网许可。被拒抛 RateLimited（不产生任何请求）。"""
        async with self._lock:
            now = time.monotonic()
            self._prune(now)

            last = self._last_request.get(domain)
            if last is not None:
                wait = self._domain_interval - (now - last)
                if wait > 0:
                    # 单域名间隔不足：等待而不是拒绝（这是"频率"不是"配额"）
                    # 等待期间不占配额
                    await asyncio.sleep(wait)
                    now = time.monotonic()

            tenant_hits = self._tenant_hits[tenant_id]
            if len(tenant_hits) >= self._tenant_rpm:
                raise RateLimited("tenant", retry_after=_retry_after(tenant_hits, now))
            if len(self._global_hits) >= self._global_rpm:
                raise RateLimited("global", retry_after=_retry_after(self._global_hits, now))

            self._last_request[domain] = now
            tenant_hits.append(now)
            self._global_hits.append(now)

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while self._global_hits and self._global_hits[0] <= cutoff:
            self._global_hits.popleft()
        for hits in self._tenant_hits.values():
            while hits and hits[0] <= cutoff:
                hits.popleft()
        stale_cutoff = now - _DOMAIN_RETENTION_SECONDS
        if len(self._last_request) > 512:
            for domain, last in list(self._last_request.items()):
                if last <= stale_cutoff:
                    del self._last_request[domain]


def _retry_after(hits: deque[float], now: float) -> float:
    if not hits:
        return _WINDOW_SECONDS
    return max(0.1, hits[0] + _WINDOW_SECONDS - now)


# 进程级单例
limiter = GuardLimiter()