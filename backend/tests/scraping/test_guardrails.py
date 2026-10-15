"""阻断级：G1-G4 四护栏测试（SPEC §9.2 AC-B3 ~ AC-B7）。

四条护栏一条不减：
- G1 robots.txt 命中即跳过，**不许绕过**、不产生请求
- G2 频率限制**服务端强制**（LLM 重试也不得突破）
- G3 UA 声明式，**不伪装浏览器**
- G4 抓取失败**显式报告**，禁止返回空日报冒充成功
- AC-B7 JS 重渲染站点必须显式失败

护栏逻辑全部在**请求发出之前**判定，因此这些测试**不需要真实网络**——
用 httpx.MockTransport 断言「有没有发出请求」，比断言返回值更强。
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.config import get_settings
from app.scraping import robots
from app.scraping.client import L1Fetcher, ScrapeError, looks_like_js_render
from app.scraping.rate_limit import GuardLimiter, RateLimited
from app.scraping.service import CompetitorScrapeService

pytestmark = pytest.mark.blocking

TENANT = uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def mock_http():
    """把 httpx.AsyncClient 换成 MockTransport 替身，并重置 robots 缓存。

    【需资深】必须先把真实类存进局部变量再打补丁：若补丁函数内部再写
    `httpx.AsyncClient(...)`，这个名字会解析到**刚打的补丁本身**，
    导致参数冲突（本次实测：got multiple values for 'transport'）。
    """
    real_client = httpx.AsyncClient
    monkey = pytest.MonkeyPatch()

    def _install(handler) -> None:
        monkey.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()

    yield _install
    monkey.undo()
    robots.cache = robots.RobotsCache()



def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ================= G1：robots.txt 合规 =================


class TestG1Robots:
    """G1：robots.txt 命中即跳过。"""

    def test_disallow_all_blocks_everything(self) -> None:
        rules, _ = robots.parse_robots("User-agent: *\nDisallow: /")
        assert robots.is_allowed(rules, "/pricing")[0] is False
        assert robots.is_allowed(rules, "/")[0] is False

    def test_specific_disallow_blocks_only_that_path(self) -> None:
        rules, _ = robots.parse_robots("User-agent: *\nDisallow: /private")
        assert robots.is_allowed(rules, "/private/x")[0] is False
        assert robots.is_allowed(rules, "/public")[0] is True

    def test_longest_match_wins(self) -> None:
        rules, _ = robots.parse_robots(
            "User-agent: *\nDisallow: /data\nAllow: /data/public"
        )
        assert robots.is_allowed(rules, "/data/secret")[0] is False
        assert robots.is_allowed(rules, "/data/public/x")[0] is True

    def test_empty_disallow_means_allow_all(self) -> None:
        rules, _ = robots.parse_robots("User-agent: *\nDisallow:")
        assert robots.is_allowed(rules, "/anything")[0] is True

    def test_named_agent_group_does_not_apply_to_us(self) -> None:
        """我们不是 Googlebot，具名 UA 分组的规则对我们不生效。"""
        rules, _ = robots.parse_robots(
            "User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin"
        )
        assert robots.is_allowed(rules, "/pricing")[0] is True
        assert robots.is_allowed(rules, "/admin/x")[0] is False

    def test_wildcard_and_anchor(self) -> None:
        rules, _ = robots.parse_robots("User-agent: *\nDisallow: /*.json$")
        assert robots.is_allowed(rules, "/data.json")[0] is False
        assert robots.is_allowed(rules, "/data.jsonx")[0] is True

    @pytest.mark.asyncio
    async def test_disallowed_site_produces_no_request(self, mock_http) -> None:
        """硬证据：robots 拒绝时**一次 HTTP 请求都不发**（连正文都不发）。"""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /")
            return httpx.Response(200, text="<html><body>should never be fetched</body></html>")

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(
                user_agent=get_settings().crawler_user_agent,
                rate_limiter=GuardLimiter(domain_interval=0),
            )
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://blocked.example.com/pricing", tenant_id=TENANT)
            assert exc.value.failure.error_code == "skipped_robots_disallowed"
            # 只有 robots.txt 一次请求，正文零请求
            assert calls == ["https://blocked.example.com/robots.txt"]
        finally:
            monkey.undo()

    @pytest.mark.asyncio
    async def test_allowed_site_is_fetched(self, mock_http) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private")
            return httpx.Response(
                200,
                text="<html><body>hello world</body></html>",
                headers={"content-type": "text/html"},
            )

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(user_agent="OPCAgentAI/1.0 (+https://x; contact=a@b.c)")
            result = await fetcher.fetch("https://ok.example.com/pricing", tenant_id=TENANT)
            assert result.status_code == 200
            assert "/pricing" in calls
        finally:
            monkey.undo()


# ================= G2：频率限制（服务端强制）=====================


class TestG2RateLimit:
    """G2：单域名 ≥2s / 单租户 ≤20rpm / 全局 ≤200rpm，服务端强制。"""

    @pytest.mark.asyncio
    async def test_same_domain_second_request_waits(self, mock_http) -> None:
        import time

        limiter = GuardLimiter(domain_interval=0.2)
        start = time.monotonic()
        await limiter.acquire(domain="a.example.com", tenant_id=str(TENANT))
        await limiter.acquire(domain="a.example.com", tenant_id=str(TENANT))
        assert time.monotonic() - start >= 0.2, "同域名第二次请求必须等待（≥2s 语义）"

    @pytest.mark.asyncio
    async def test_different_domains_do_not_block_each_other(self, mock_http) -> None:
        limiter = GuardLimiter(domain_interval=5.0)
        await limiter.acquire(domain="a.example.com", tenant_id=str(TENANT))
        await limiter.acquire(domain="b.example.com", tenant_id=str(TENANT))  # 不等待

    @pytest.mark.asyncio
    async def test_tenant_rpm_limit_enforced(self, mock_http) -> None:
        limiter = GuardLimiter(domain_interval=0, tenant_rpm=3)
        for i in range(3):
            await limiter.acquire(domain=f"d{i}.example.com", tenant_id=str(TENANT))
        with pytest.raises(RateLimited) as exc:
            await limiter.acquire(domain="d9.example.com", tenant_id=str(TENANT))
        assert exc.value.scope == "tenant"

    @pytest.mark.asyncio
    async def test_global_rpm_limit_enforced(self, mock_http) -> None:
        limiter = GuardLimiter(domain_interval=0, tenant_rpm=100, global_rpm=2)
        await limiter.acquire(domain="a.example.com", tenant_id="tenant-a")
        await limiter.acquire(domain="b.example.com", tenant_id="tenant-b")
        with pytest.raises(RateLimited) as exc:
            await limiter.acquire(domain="c.example.com", tenant_id="tenant-c")
        assert exc.value.scope == "global"

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_before_any_request(self, mock_http) -> None:
        """被限流时**正文零请求**（服务端强制，不靠 Agent 自觉）。

        robots.txt 允许发出：它是合规前提且有缓存（每域名至多一次），
        限流管的是正文抓取频率。断言 robots.txt 恰好一次、正文零次。
        """
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(
                200,
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html"},
            )

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(
                user_agent="OPCAgentAI/1.0 (+https://x; contact=a@b.c)",
                rate_limiter=GuardLimiter(domain_interval=0, tenant_rpm=1),
            )
            await fetcher.fetch("https://x.example.com/a", tenant_id=TENANT)
            calls.clear()
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://y.example.com/b", tenant_id=TENANT)
            assert exc.value.failure.error_code == "rate_limited_tenant"
            assert calls == ["https://y.example.com/robots.txt"], (
                "被限流时正文不应有请求（robots.txt 属合规检查且有缓存，允许发出）"
            )
        finally:
            monkey.undo()


# ================= G3：UA 声明 =================


class TestG3UserAgent:
    """G3：声明 OPCAgentAI 身份，不伪装浏览器。"""

    def test_configured_ua_is_identifiable(self) -> None:
        ua = get_settings().crawler_user_agent
        assert ua.startswith("OPCAgentAI/")
        assert "contact=" in ua
        assert "+https://" in ua

    @pytest.mark.parametrize(
        "browser_ua",
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1",
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ],
    )
    def test_platform_ua_is_not_a_browser(self, browser_ua: str) -> None:
        ua = get_settings().crawler_user_agent
        assert ua != browser_ua
        assert "Mozilla" not in ua
        assert not any(b in ua for b in ("Chrome", "Safari", "Firefox"))

    @pytest.mark.asyncio
    async def test_request_carries_declared_ua(self, mock_http) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("user-agent", ""))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(
                200, text="<html><body>x</body></html>", headers={"content-type": "text/html"}
            )

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(
                user_agent=get_settings().crawler_user_agent,
                rate_limiter=GuardLimiter(domain_interval=0),
            )
            await fetcher.fetch("https://ua.example.com/p", tenant_id=TENANT)
        finally:
            monkey.undo()
        assert seen and all(ua.startswith("OPCAgentAI/") for ua in seen), seen


# ================= G4：失败显式化 =================


class TestG4ExplicitFailure:
    """G4：失败必须显式报告，禁止空日报冒充成功。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "expected_code"),
        [(500, "http_5xx"), (503, "http_5xx"), (404, "http_4xx"), (403, "http_4xx")],
    )
    async def test_http_error_maps_to_explicit_failure(
        self, mock_http, status: int, expected_code: str
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(status, text="")

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)")
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://err.example.com/p", tenant_id=TENANT)
            assert exc.value.failure.error_code == expected_code
            assert exc.value.failure.user_message  # 业务语言，非空
        finally:
            monkey.undo()

    @pytest.mark.asyncio
    async def test_timeout_maps_to_explicit_failure(self, mock_http) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            raise httpx.ReadTimeout("too slow", request=request)

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)")
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://slow.example.com/p", tenant_id=TENANT)
            assert exc.value.failure.error_code == "timeout"
            assert exc.value.failure.retryable is True
        finally:
            monkey.undo()

    @pytest.mark.asyncio
    async def test_empty_content_is_failure_not_empty_success(self, mock_http) -> None:
        """空内容必须失败——「今天没有异常」是最危险的伪造成功（G4）。"""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(200, text="", headers={"content-type": "text/html"})

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)")
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://empty.example.com/p", tenant_id=TENANT)
            assert exc.value.failure.error_code == "empty_content"
        finally:
            monkey.undo()

    @pytest.mark.asyncio
    async def test_non_html_content_type_fails_explicitly(self, mock_http) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            fetcher = L1Fetcher(user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)")
            with pytest.raises(ScrapeError) as exc:
                await fetcher.fetch("https://pdf.example.com/p", tenant_id=TENANT)
            assert exc.value.failure.error_code == "unsupported_content_type"
        finally:
            monkey.undo()

    @pytest.mark.asyncio
    async def test_partial_failure_still_reports_others(self, mock_http) -> None:
        """部分成功语义（AC-9）：成功的保留、失败的显式列出，两边都不丢。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            if "broken" in request.url.host:
                return httpx.Response(500, text="")
            return httpx.Response(
                200,
                text="<html><head><title>Pricing</title></head><body>"
                "<h1>Standard Plan</h1><p>价格 ¥99 / 月</p>"
                "<p>" + "内容" * 200 + "</p></body></html>",
                headers={"content-type": "text/html"},
            )

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            service = CompetitorScrapeService(
                user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)",
                rate_limiter=GuardLimiter(domain_interval=0),
            )
            report = await service.run(
                tenant_id=TENANT,
                urls=["https://good.example.com/pricing", "https://broken.example.com/pricing"],
            )
            assert report.total == 2
            assert report.ok_count == 1
            assert report.failed_count == 1
            assert report.failures[0].domain == "broken.example.com"
            # 成功的那站必须有解析结果（不丢成果）
            assert any(s.ok and s.facts for s in report.sites)
        finally:
            monkey.undo()


# ================= AC-B7：JS 重渲染 =================


class TestJsRenderDetection:
    """AC-B7：需要 JS 渲染的站点必须显式失败，禁止静默返回空内容。"""

    def test_spa_shell_detected(self) -> None:
        html = '<html><body><div id="root"></div><script>window.__NEXT_DATA__={}</script></body></html>'
        assert looks_like_js_render(html) is True

    def test_ng_app_detected(self) -> None:
        assert looks_like_js_render('<html><body><app-root ng-app></app-root></body></html>') is True

    def test_server_rendered_page_not_flagged(self) -> None:
        html = "<html><body><h1>竞品价格</h1><p>" + "真实内容" * 300 + "</p></body></html>"
        assert looks_like_js_render(html) is False

    @pytest.mark.asyncio
    async def test_js_site_reports_target_requires_js_render(self, mock_http) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow:")
            return httpx.Response(
                200,
                text='<html><body><div id="root"></div><script>__NEXT_DATA__</script></body></html>',
                headers={"content-type": "text/html"},
            )

        real_client = httpx.AsyncClient  # 先存真身：setattr 后裸名 httpx.AsyncClient 解析到补丁自身（见 mock_http docstring）
        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            "app.scraping.client.httpx.AsyncClient",
            lambda **kw: real_client(transport=_transport(handler), **kw),
        )
        robots.cache = robots.RobotsCache()
        try:
            service = CompetitorScrapeService(
                user_agent="OPCAgentAI/1.0 (+x; contact=a@b.c)",
                rate_limiter=GuardLimiter(domain_interval=0),
            )
            report = await service.run(tenant_id=TENANT, urls=["https://spa.example.com/"])
            assert report.failed_count == 1
            assert report.failures[0].error_code == "TARGET_REQUIRES_JS_RENDER"
        finally:
            monkey.undo()