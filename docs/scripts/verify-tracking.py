#!/usr/bin/env python3
"""埋点白名单三方一致性门禁（PM TRACKING-GUARD 方案 / SPEC §9.8）。

双向差集：代码 ALLOWED_EVENTS ↔ TRACKING-WHITELIST.md ↔ openapi enum。
任一方向有差异即阻断（退出码 1）。

为什么这道门禁必须存在：白名单文档是给人和 AI 看的，代码是给解释器看的。
两者的不一致不会报错，只会**静默地让一边失效**——所有人还以为它在生效。

用法（仓库根目录）：
    python docs/scripts/verify-tracking.py
依赖：无第三方包（标准库）。
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
WHITELIST_MD = ROOT / "docs" / "TRACKING-WHITELIST.md"
OPENAPI_YAML = ROOT / "docs" / "openapi.yaml"

EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")


def events_from_code() -> set[str]:
    """从 app.analytics.events import ALLOWED_EVENTS（单一数据源，直接 import）。"""
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.analytics.events import ALLOWED_EVENTS;"
            " print('\\n'.join(sorted(ALLOWED_EVENTS)))",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def events_from_whitelist_md() -> set[str]:
    """提取 TRACKING-WHITELIST.md 事件表格第一列的 `event_name`。

    排除「已删除/作废」说明区的行（留痕章节允许保留历史事件名）。
    """
    text = io.open(WHITELIST_MD, encoding="utf-8").read()
    # 截掉作废/删除说明章节（该区域允许历史事件名留痕）
    for marker in ("## 作废", "## 已删除", "## 已剔除"):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    names: set[str] = set()
    for line in text.splitlines():
        # 只取表格行**第一列**（事件名列）；第三列的属性名（`agent_id` 等）不算事件
        row = re.match(r"\|\s*`([a-z][a-z0-9_]{2,60})`\s*\|", line)
        if row:
            names.add(row.group(1))
    return names


def events_from_openapi() -> set[str]:
    """提取 openapi.yaml 中 name 字段的 enum 值（埋点请求体唯一 enum）。"""
    text = io.open(OPENAPI_YAML, encoding="utf-8").read()
    # 定位埋点请求 schema 的 name enum（name: → type: string → [description: | ...] → enum:）
    m = re.search(
        r"name:\s*\n\s*type:\s*string\s*\n(?:\s+description:\s*\|?\s*\n(?:.*\n)*?)?\s*enum:\s*\n((?:\s*-\s*[a-z_]+\n)+)",
        text,
    )
    if not m:
        raise SystemExit("FAIL: openapi.yaml 未找到埋点 name enum（契约缺口）")
    return set(re.findall(r"-\s*([a-z][a-z0-9_]{2,60})", m.group(1)))


def main() -> int:
    code = events_from_code()
    md = events_from_whitelist_md()
    api = events_from_openapi()

    problems: list[str] = []

    only_md = md - code
    only_code = code - md
    if only_md:
        problems.append(
            f"白名单文档多出 {len(only_md)} 个（代码已删/文档未清）: {sorted(only_md)}"
        )
    if only_code:
        problems.append(
            f"代码多出 {len(only_code)} 个（文档漏记，前端不可见）: {sorted(only_code)}"
        )

    only_api = api - code
    only_code_api = code - api
    if only_api:
        problems.append(
            f"openapi enum 多出 {len(only_api)} 个（与代码 ALLOWED_EVENTS 不一致）: {sorted(only_api)}"
        )
    if only_code_api:
        problems.append(
            f"代码多出 {len(only_code_api)} 个（openapi enum 未同步，契约层防线失效）: {sorted(only_code_api)}"
        )

    print(f"代码 ALLOWED_EVENTS: {len(code)} 个")
    print(f"TRACKING-WHITELIST.md: {len(md)} 个")
    print(f"openapi name enum: {len(api)} 个")

    if problems:
        print("\n== 门禁失败：三方不一致 ==")
        for p in problems:
            print(f"- {p}")
        print(
            "\n修复规则：以代码 ALLOWED_EVENTS 为准——文档删掉多余行，"
            "openapi enum 补齐缺失项。删除功能时连白名单行一起删（DECISION-CHANGES 规则）。"
        )
        return 1

    print("三方一致，门禁通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
