"""竞品监控日报抓取编排：多站点 → 结构化结果 + **显式失败清单**（G4）。

G4 是四条护栏里最重要的一条：最危险的失败模式不是「抓不到」，而是
**「抓不到但报告说今天没有异常」**——老板会据此做商业决策。
因此本模块的契约是：**任何站点失败都必须出现在 failures 列表里，
绝不静默丢弃，也绝不用空结果冒充成功。**

【需资深】修改本文件前先读 SPEC §4.5 的 G4 与 §9.2 AC-B6/AC-B7。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.scraping.client import (
    L1Fetcher,
    ScrapeError,
    ScrapeFailure,
    ScrapeResult,
    looks_like_js_render,
)
from app.scraping.parser import PageFacts, parse_page
from app.scraping.rate_limit import GuardLimiter, limiter

logger = get_logger("scraping.service")

# 单次任务最多抓多少个站点（SPEC §2.4 岗位步骤数 3-8，此处为安全上限）
MAX_URLS_PER_RUN = 20


@dataclass
class SiteReport:
    """单站点的抓取结果（成功或失败，二选一）。"""

    url: str
    domain: str
    ok: bool
    facts: PageFacts | None = None
    failure: ScrapeFailure | None = None
    content_hash: str | None = None


@dataclass
class ScrapeReport:
    """一次抓取任务的汇总。

    failures 非空 = 汇报必须显式列出这些站点（G4）。
    ok_count + failed_count == len(urls)，不允许有第三种结果。
    """

    total: int
    ok_count: int
    sites: list[SiteReport] = field(default_factory=list)
    failures: list[ScrapeFailure] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


class CompetitorScrapeService:
    """竞品监控日报的抓取编排。

    依赖注入 fetcher：测试可替换为不触网的假实现（护栏另有独立测试）。
    """

    def __init__(
        self, *, user_agent: str, fetcher: L1Fetcher | None = None,
        rate_limiter: GuardLimiter | None = None,
    ) -> None:
        self._fetcher = fetcher or L1Fetcher(
            user_agent=user_agent, rate_limiter=rate_limiter or limiter
        )

    async def run(self, *, tenant_id: uuid.UUID, urls: list[str]) -> ScrapeReport:
        """抓取全部目标站点。失败不中断整体，逐站记录（部分成功语义，AC-9）。"""
        targets = urls[:MAX_URLS_PER_RUN]
        if len(urls) > MAX_URLS_PER_RUN:
            logger.warning(
                "scrape_targets_truncated",
                tag="scrape_targets_truncated",
                requested=len(urls),
                allowed=MAX_URLS_PER_RUN,
            )

        results = await asyncio.gather(
            *(self._fetch_one(tenant_id, url) for url in targets), return_exceptions=False
        )
        sites = [r for r in results if isinstance(r, SiteReport)]
        failures = [r.failure for r in sites if r.failure is not None]
        return ScrapeReport(
            total=len(targets),
            ok_count=len(targets) - len(failures),
            sites=sites,
            failures=failures,
        )

    async def _fetch_one(self, tenant_id: uuid.UUID, url: str) -> SiteReport:
        try:
            result: ScrapeResult = await self._fetcher.fetch(url, tenant_id=tenant_id)
        except ScrapeError as exc:
            return SiteReport(
                url=url, domain=exc.failure.domain, ok=False, failure=exc.failure
            )

        # AC-B7：JS 重渲染站点必须显式失败，禁止静默空内容
        if looks_like_js_render(result.html):
            failure = ScrapeFailure(
                url=result.url,
                domain=result.domain,
                error_code="TARGET_REQUIRES_JS_RENDER",
                user_message=(
                    f"{result.domain} 的页面要在浏览器里才显示内容，我这层拿不到，"
                    "没法判断今天有没有变化。"
                ),
                http_status=result.status_code,
            )
            logger.warning(
                "js_render_required", tag="js_render_required", domain=result.domain
            )
            return SiteReport(
                url=result.url, domain=result.domain, ok=False, failure=failure
            )

        try:
            facts = parse_page(result.html, result.url)
        except Exception as exc:
            failure = ScrapeFailure(
                url=result.url,
                domain=result.domain,
                error_code="parse_failed",
                user_message=f"{result.domain} 的页面结构我读不懂，这次没分析出来。",
                http_status=result.status_code,
            )
            logger.warning(
                "page_parse_failed", domain=result.domain, error_type=type(exc).__name__
            )
            return SiteReport(url=result.url, domain=result.domain, ok=False, failure=failure)

        return SiteReport(
            url=result.url,
            domain=result.domain,
            ok=True,
            facts=facts,
            content_hash=result.content_hash,
        )


def build_service(user_agent: str) -> CompetitorScrapeService:
    return CompetitorScrapeService(user_agent=user_agent)


__all__ = [
    "CompetitorScrapeService",
    "ScrapeReport",
    "SiteReport",
    "build_service",
    "limiter",
]