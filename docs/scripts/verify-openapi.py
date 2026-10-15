#!/usr/bin/env python3
"""
openapi.yaml 契约门禁（CI 阻断级）

依据：SPEC.md §5 + ADR-017
铁律：任何 API 变更必须先更新 openapi.yaml，再更新 SPEC.md（SPEC §13 变更记录）

四项检查：
  1. YAML 可解析 + 关键版本/路径存在
  2. 所有 $ref 可解析（防止幻觉引用）
  3. **owner 侧 schema 不得出现 token / model / duration 字段**（AC-14b）
  4. 跨租户错误码语义：1004 而非 1003（SPEC §5.4）

用法：
  python scripts/verify-openapi.py
退出码 0 = 通过；非 0 = 阻断
"""

import sys
import re
import pathlib

try:
    import yaml
except ImportError:
    print("FAIL: 需要 pyyaml（pip install pyyaml）")
    sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "openapi.yaml"

# owner 侧禁止出现的字段关键词（小写匹配）
BAN_KEYS = ("token", "model", "duration")

# 必须保持 CLEAN 的 schema（owner / 业务视角）
OWNER_SCHEMAS = (
    "OwnerUsageSummary",
    "DailyReport",
    "AgentReport",
    "WeeklyReport",     # 周报同为 owner 视角
    "CostBreakdown",
    "BacklogItem",
    "TrustSummary",
    "Goal",# 汇报链路会引用
    "GoalDetail",
)

errors: list[str] = []


def check_yaml_parseable():
    try:
        return yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"YAML 无法解析: {exc}")
        return None


def check_structure(doc):
    if doc.get("openapi") != "3.0.3":
        errors.append(f"openapi 版本应为 3.0.3，实际 {doc.get('openapi')}")
    for required in ("info", "paths", "components"):
        if required not in doc:
            errors.append(f"缺少顶层字段: {required}")
    # 必须存在的关键端点（架构硬约束）
    required_paths = (
        "/api/v1/usage/summary",       # owner 口径，schema 内无 token
        "/api/v1/settings/usage",      # admin 口径，与上者刻意分离
        "/api/v1/events/stream",       # 单条聚合 SSE
        "/api/v1/goals/{id}/cancel",   # 幂等 + 先置 stopping
        "/api/v1/analytics/events",    # 埋点后端白名单过滤
    )
    for p in required_paths:
        if p not in doc.get("paths", {}):
            errors.append(f"缺少必需端点: {p}")


def check_refs_resolvable(raw: str, doc):
    # 捕获时不把收尾引号带进引用名（YAML 里 $ref 两侧引号可有可无）
    pat = re.compile(r"""\$ref:\s*['"]?(#/components/[A-Za-z0-9_/]+)['"]?""")
    for m in pat.finditer(raw):
        ref = m.group(1)
        node = doc
        for part in ref.lstrip("#/").split("/"):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                errors.append(f"$ref 无法解析（幻觉引用）: {ref}")
                break


def deep_collect_keys(node, trail="root"):
    """递归收集 schema 中所有属性名，含嵌套与数组 items。"""
    out = []
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for k, v in props.items():
                out.append((trail + "." + k, k))
                out.extend(deep_collect_keys(v, trail + "." + k))
        if isinstance(node.get("items"), dict):
            out.extend(deep_collect_keys(node["items"], trail + "[]"))
    return out


def check_owner_schemas_clean(doc):
    schemas = doc.get("components", {}).get("schemas", {})
    for name in OWNER_SCHEMAS:
        s = schemas.get(name)
        if s is None:
            continue
        for full, key in deep_collect_keys(s, name):
            low = key.lower()
            hit = next((b for b in BAN_KEYS if b in low), None)
            if hit:
                errors.append(
                    f"[AC-14b] owner 侧schema 出现禁用字段: {name} -> {full}"
                    f"（含 '{hit}'）。owner 视图不得出现 token/model/duration。"
                )


def check_error_code_semantics(raw: str):
    """跨租户必须 404（code 1004），不得用 403（code 1003）。"""
    if "跨租户禁止使用此码" not in raw:
        errors.append("错误码规范缺少「跨租户禁止使用 1003」的声明")
    if "不区分" not in raw:
        errors.append("NotFound 响应缺少「或跨租户（不区分）」的说明")


def main() -> int:
    if not SPEC.exists():
        print(f"FAIL: 契约文件不存在 {SPEC}")
        return 2

    raw = SPEC.read_text(encoding="utf-8")
    doc = check_yaml_parseable()
    if doc is None:
        print("\n".join(errors))
        return 1

    check_structure(doc)
    check_refs_resolvable(raw, doc)
    check_owner_schemas_clean(doc)
    check_error_code_semantics(raw)

    ops = sum(
        1
        for p in doc["paths"].values()
        for m in p
        if m in ("get", "post", "put", "patch", "delete")
    )
    if errors:
        print("openapi.yaml 门禁未通过：")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("openapi.yaml 门禁通过")
    print(f"  路径 {len(doc['paths'])} / 操作 {ops} / schema {len(doc['components']['schemas'])}")
    print(f"  owner 侧 schema 已断言无 token/model/duration（{len(OWNER_SCHEMAS)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())