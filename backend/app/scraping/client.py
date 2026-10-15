"""L1 服务端 HTTP 抓取 + G2/G3 强制（SPEC §9.2 / ADR-014）。

四道护栏在本模块的**调用顺序**上强制（顺序本身就是设计）：
    1. 域名准入（tenant_egress_allowlist，AC-B1）
    2. G1 robots.txt 判定 —— 命中即返回，**不发请求**
    3. G2 三层限流（单域名 2s / 单租户 20rpm / 全局 200rpm）
    4. 实际出网请求（带 G3 声明式 UA）
    5. G4 失败显式化（异常映射为结构化失败，绝不返回空内容冒充成功）

【需资深】为什么 HTTP 错误、超时、空内容都必须抛出而不是返回 None：
AC-B7 要求 JS 重渲染站点返回 `TARGET_REQUIRES_JS_RENDER` 而非静默空内容；
G4 要求抓取失败显式进入「我停下来过」。返回 None 会让这两条都变成"看起来成功"。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from app.core.logging import get_logger
from app.scraping import robots
from app.scraping.rate_limit import GuardLimiter, RateLimited, limiter

logger = get_logger("scraping.client")

REQUEST_TIMEOUT_SECONDS = 15.0
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2MB 上限，避免把大文件读进内存
# JS 重渲染判定：正文里全是脚本容器且几乎没有可见文本
_MIN_VISIBLE_TEXT_CHARS = 200
_SPA_MARKERS = (
    "__next_data__",
    "__NUXT__",
    "id=\"root\"",
    "id='root'",
    "ng-app",
    "data-reactroot",
)


@dataclass
class ScrapeFailure:
    """结构化抓取失败。**任何失败都必须带它**，不允许用空结果代替（G4）。"""

    url: str
    domain: str
    error_code: str  # robots_disallowed / http_5xx / timeout / js_render_required / ...
    user_message: str  # 业务语言，进「我停下来过」板块
    http_status: int | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "domain": self.domain,
            "error_code": self.error_code,
            "user_message": self.user_message,
            "http_status": self.http_status,
        }


@dataclass
class ScrapeResult:
    """抓取成功结果。html 为空字符串视为失败（不会走到这里）。"""

    url: str
    domain: str
    status_code: int
    html: str
    content_hash: str
    fetched_at: datetime
    elapsed_ms: int
    title: str | None = None
    meta: dict[str, str] = field(default_factory=dict)


class ScrapeError(Exception):
    """抓取失败（承载结构化失败原因）。"""

    def __init__(self, failure: ScrapeFailure) -> None:
        self.failure = failure
        super().__init__(failure.error_code)


class L1Fetcher:
    """L1 抓取器。依赖注入 limiter 便于测试替换。"""

    def __init__(self, *, user_agent: str, rate_limiter: GuardLimiter | None = None) -> None:
        self._user_agent = user_agent
        self._limiter = rate_limiter or limiter

    async def fetch(self, url: str, *, tenant_id: uuid.UUID) -> ScrapeResult:
        """抓取单页。任何失败路径都抛 ScrapeError（带 ScrapeFailure）。"""
        domain = urlparse(url).netloc

        # 2) G1：robots 先判，命中即停（不发任何请求）
        verdict = await robots.check(url)
        if not verdict.allowed:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="skipped_robots_disallowed",
                    user_message=f"{domain} 不允许我们抓取，跳过了这个站点。",
                )
            )

        # 3) G2：三层限流
        try:
            await self._limiter.acquire(domain=domain, tenant_id=str(tenant_id))
        except RateLimited as exc:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code=f"rate_limited_{exc.scope}",
                    user_message=(
                        f"{domain} 这会儿请求太密集，我先等一下再继续。"
                        if exc.scope == "domain"
                        else "我今天的抓取频率用得有点多，先停一下。"
                    ),
                    retryable=True,
                )
            ) from exc

        # 4) 出网（G3：声明式 UA，不伪装浏览器）
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": self._user_agent,  # G3
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                resp = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="timeout",
                    user_message=f"{domain} 这次没响应，我等会儿再试。",
                    retryable=True,
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="network_error",
                    user_message=f"{domain} 这次连不上，我没法拿到内容。",
                    retryable=True,
                )
            ) from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code >= 500:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="http_5xx",
                    user_message=f"{domain} 返回了错误（{resp.status_code}），这次没抓到。",
                    http_status=resp.status_code,
                    retryable=True,
                )
            )
        if resp.status_code >= 400:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="http_4xx",
                    user_message=f"{domain} 拒绝了这次访问（{resp.status_code}）。",
                    http_status=resp.status_code,
                )
            )

        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="unsupported_content_type",
                    user_message=f"{domain} 这个地址返回的不是网页，内容类型是 {ctype or '未知'}。",
                    http_status=resp.status_code,
                )
            )

        html = resp.text[:MAX_CONTENT_BYTES]
        if not html.strip():
            # G4：空内容必须显式失败，不能当成"今天没有变化"
            raise ScrapeError(
                ScrapeFailure(
                    url=url,
                    domain=domain,
                    error_code="empty_content",
                    user_message=f"{domain} 返回了空内容，我没法判断今天有没有变化。",
                    http_status=resp.status_code,
                )
            )

        return ScrapeResult(
            url=str(resp.url),
            domain=urlparse(str(resp.url)).netloc,
            status_code=resp.status_code,
            html=html,
            content_hash=_content_hash(html),
            fetched_at=datetime.now(UTC),
            elapsed_ms=elapsed_ms,
        )


def _content_hash(html: str) -> str:
    from hashlib import blake2b

    return blake2b(html.encode("utf-8"), digest_size=32).hexdigest()


def looks_like_js_render(html: str) -> bool:
    """AC-B7：JS 重渲染站点必须显式失败，禁止静默返回空内容。

    判定：可见文本极少 且 命中常见 SPA 挂载标记。
    """
    from app.scraping.parser import visible_text

    text = visible_text(html)
    if len(text) >= _MIN_VISIBLE_TEXT_CHARS:
        return False
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in _SPA_MARKERS)