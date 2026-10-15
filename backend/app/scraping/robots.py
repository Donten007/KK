"""G1：robots.txt 合规（SPEC §4.5 / AC-B3）。

铁律：**Disallow 命中即跳过，不许绕过**，且不产生任何对该站的请求。
robots 结果按域名缓存（TTL 1 小时），既减少请求量也符合 robots 协议
（爬虫应缓存 robots.txt）。

【需资深】为什么要自己解析而不用 urllib.robotparser：
1. urllib.robotparser 的 allow_all/disallow_all 判定在「空规则」情况下
   默认放行，我们需要的是「取不到 robots.txt 时按放行但记录 warning，
   robots.txt 明确 Disallow 时绝不请求」这一可审计语义
2. 需要把判定结果落库（G4 要显式报告"因 robots 被跳过"），stdlib 不产出结构化结果
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from app.core.logging import get_logger

logger = get_logger("scraping.robots")

# G3 声明式 UA：同一身份出现在 robots 请求与正文请求，避免两种身份
ROBOTS_UA = "OPCAgentAI/1.0 (+https://opcagentai.com/bot; contact=ops@opcagentai.com)"
ROBOTS_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 3600.0


@dataclass
class RobotsVerdict:
    """robots 判定结果（结构化，便于落库与汇报）。"""

    allowed: bool
    reason: str  # ok / robots_disallowed / robots_unreachable
    matched_rule: str | None = None
    crawl_delay: float | None = None


@dataclass
class _CacheEntry:
    rules: list[tuple[str, bool]]  # (pattern, is_disallow)
    crawl_delay: float | None
    fetched_at: float
    reachable: bool = field(default=False)


class RobotsCache:
    """按域名缓存 robots 规则。进程内缓存，多 worker 部署时各自一份（TTL 内一致）。"""

    def __init__(self, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._ttl = ttl
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, origin: str) -> asyncio.Lock:
        if origin not in self._locks:
            self._locks[origin] = asyncio.Lock()
        return self._locks[origin]

    async def get_rules(self, origin: str) -> _CacheEntry:
        entry = self._entries.get(origin)
        if entry and (time.monotonic() - entry.fetched_at) < self._ttl:
            return entry

        async with self._lock_for(origin):
            # 双检：等锁期间可能已被其他协程填充
            entry = self._entries.get(origin)
            if entry and (time.monotonic() - entry.fetched_at) < self._ttl:
                return entry
            entry = await self._fetch(origin)
            self._entries[origin] = entry
            return entry

    async def _fetch(self, origin: str) -> _CacheEntry:
        robots_url = f"{origin}/robots.txt"
        try:
            async with httpx.AsyncClient(
                timeout=ROBOTS_TIMEOUT_SECONDS,
                headers={"User-Agent": ROBOTS_UA},
                follow_redirects=True,
            ) as client:
                resp = await client.get(robots_url)
        except Exception as exc:
            # robots.txt 取不到：按放行处理但记录 warning（robots 协议允许），
            # 真正无法访问的站点会在正文请求时暴露为 G4 失败
            logger.warning(
                "robots_unreachable", tag="robots_unreachable", origin=origin, error=str(exc)
            )
            return _CacheEntry(rules=[], crawl_delay=None, fetched_at=time.monotonic())

        if resp.status_code >= 400:
            # 404/5xx：视为无 robots 限制（robots 协议惯例）
            logger.info(
                "robots_absent", origin=origin, status=resp.status_code
            )
            return _CacheEntry(
                rules=[], crawl_delay=None, fetched_at=time.monotonic(), reachable=True
            )

        rules, crawl_delay = parse_robots(resp.text)
        logger.info("robots_loaded", origin=origin, rules=len(rules), crawl_delay=crawl_delay)
        return _CacheEntry(
            rules=rules, crawl_delay=crawl_delay, fetched_at=time.monotonic(), reachable=True
        )


def parse_robots(text_body: str) -> tuple[list[tuple[str, bool]], float | None]:
    """解析 robots.txt。返回 (规则列表, crawl_delay)。

    只取 User-agent: * 分组（我们的 UA 不与任何具名 UA 匹配，robots 协议里
    `*` 组对未列出的 UA 生效）。
    """
    rules: list[tuple[str, bool]] = []
    crawl_delay: float | None = None
    in_star_group = False
    expecting_group = False

    for raw_line in text_body.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            # 连续的 user-agent 行属于同一组；出现其他指令后遇到新 user-agent 即新组
            if not expecting_group:
                in_star_group = False
            expecting_group = True
            if value == "*":
                in_star_group = True
            continue

        expecting_group = False
        if not in_star_group:
            continue
        if field_name == "disallow":
            # 空 Disallow 表示允许全部，忽略该行
            if value:
                rules.append((value, True))
        elif field_name == "allow":
            if value:
                rules.append((value, False))
        elif field_name == "crawl-delay":
            # 非 float 的 crawl-delay（如某些站点写 "5, 10"）按规范忽略
            with suppress(ValueError):
                crawl_delay = float(value)
    return rules, crawl_delay


def is_allowed(rules: list[tuple[str, bool]], path: str) -> tuple[bool, str | None]:
    """判定 path 是否被允许。**最长匹配优先**（robots 协议标准语义）。

    Allow 与 Disallow 同时匹配时，长度更长者胜；同长度时 Allow 优先。
    """
    best: tuple[int, bool] | None = None  # (匹配长度, 是否允许)
    best_rule: str | None = None
    for pattern, is_disallow in rules:
        if _pattern_matches(pattern, path):
            length = len(pattern)
            if best is None or length > best[0] or (length == best[0] and not is_disallow):
                best = (length, not is_disallow)
                best_rule = pattern
    if best is None:
        return True, None
    return best[1], best_rule


def _pattern_matches(pattern: str, path: str) -> bool:
    """robots 路径匹配：支持 * 通配与 $ 行尾锚（SPEC 要求的最小实现集）。"""
    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else ("\\" + ch if ch in "^$.?+()[]{}|\\" else ch) for ch in core)
    return _full_match(f"^{regex}" + ("$" if anchored else ""), path)


def _full_match(regex: str, text: str) -> bool:
    import re

    return re.match(regex, text) is not None


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# 进程级缓存
cache = RobotsCache()


async def check(url: str) -> RobotsVerdict:
    """G1 判定入口：命中 Disallow 即返回 allowed=False，调用方**不得**发起正文请求。"""
    origin = origin_of(url)
    path = urlparse(url).path or "/"
    entry = await cache.get_rules(origin)
    allowed, matched = is_allowed(entry.rules, path)
    if not allowed:
        logger.warning(
            "robots_disallowed", tag="robots_disallowed", origin=origin, path=path, rule=matched
        )
        return RobotsVerdict(allowed=False, reason="robots_disallowed", matched_rule=matched)
    reason = "ok" if entry.reachable else "robots_unreachable"
    return RobotsVerdict(allowed=True, reason=reason, crawl_delay=entry.crawl_delay)