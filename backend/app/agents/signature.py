"""工具调用签名归一化（ADR-016 / AC-17 的核心修正）。

原设计签名只含 tool_name，会把「下载 50 个竞品页面」（fetch_url→parse_html
交替、url 每次不同）误判为死循环并在第 5 步熔断——这类合法周期性工作极常见。

正确签名 = tool_name + 归一化参数摘要：
- 循环索引参数（url/page/index/offset/id）**保留原值**——区分「循环推进」
  与「原地打转」正是靠它们
- 内容参数用哈希（内容每次都变），且必须用**跨进程稳定**的哈希

【需资深】为什么不用 SPEC 示例里的 `hash(v)`：Python 内置 hash 对 str 加盐
（PYTHONHASHSEED），同一参数在不同进程得到不同哈希值。而 seen_tool_windows
要落库并在崩溃重启后复用——用内置 hash 会导致「重启前后签名不可比」，
检测窗口形同虚设。故用 blake2b（快、抗碰撞、无随机盐）。
"""

from __future__ import annotations

import json
from hashlib import blake2b
from typing import Any

# 循环索引参数：保留原值（ADR-011 §3 / SPEC §4.6）
PATH_LIKE_KEYS = frozenset({"url", "page", "index", "offset", "id"})

_HASH_LEN = 12  # blake2b 截断长度：12 hex ≈ 48 bit，足够区分参数


def _stable_digest(value: Any) -> str:
    """跨进程稳定的内容哈希。"""
    try:
        canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = repr(value)
    return blake2b(canonical.encode("utf-8"), digest_size=6).hexdigest()


def normalize_args(args: dict[str, Any]) -> str:
    """参数归一化摘要。key 排序保证同一组参数永远得到同一字符串。"""
    if not args:
        return ""
    parts: list[str] = []
    for key in sorted(args):
        value = args[key]
        if key in PATH_LIKE_KEYS:
            parts.append(f"{key}={value}")
        else:
            parts.append(f"{key}={_stable_digest(value)}")
    return ",".join(parts)


def tool_signature(tool_name: str, args: dict[str, Any]) -> str:
    """工具名 + 归一化参数摘要。参数不同则签名不同（ADR-016 修正后）。"""
    return f"{tool_name}({normalize_args(args)})"


def legacy_tool_signature(tool_name: str, args: dict[str, Any] | None = None) -> str:
    """仅含 tool_name 的旧签名 —— **仅供 AC-17 用例 ③ 做修正前后对比**。

    生产路径禁止调用：它会误杀「下载 50 个页面」这类合法周期性工作。
    """
    return tool_name


def window_hash(signatures: list[str]) -> str:
    """K 步签名的窗口哈希。"""
    return _stable_digest(signatures)


def signature_streak(signatures: list[str]) -> int:
    """末尾连续相同签名的长度（静态死循环判定）。"""
    if not signatures:
        return 0
    last = signatures[-1]
    count = 0
    for sig in reversed(signatures):
        if sig != last:
            break
        count += 1
    return count