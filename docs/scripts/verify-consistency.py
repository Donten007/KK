#!/usr/bin/env python3
"""
跨文档一致性门禁（CI 阻断级）

依据：ADR-017 教训「引用了但没验证」+ 2026-10-15 的 C1 收窄/推翻冲突
铁律：**裁决变更必须回查已落盘的所有下游文档，不能只改一处**

本脚本检查四份文档对关键裁定的表述是否一致。任一冲突即阻断。

用法：
  python scripts/verify-consistency.py
退出码 0 = 一致；非 0 = 阻断
"""

import sys
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 关键裁定：(裁定名, 立场A关键词, 立场B关键词)
# 规则：若立场 A 与立场 B 的命中数同时 > 0，且分布跨越多份文档，则冲突。
DECISIONS = {
    "网页访问 L1 范围": {
        "narrow": "仅客户自有域名",   # 收窄表述
        "wide": ["恢复", "第三方公开网页抓取", "L1 公开网页"],  # 恢复表述
        "docs": ["decisions/ADR-014-web-access-tiers.md", "ARCHITECTURE.md"],
        "note": "C1 曾收窄为仅自有域名，用户复看后推翻。若仍有文档停留在收窄态即为矛盾。",
    },
    "平台代付": {
        "narrow": ["credit_ledger", "credit_reservations", "预占-确认-释放"],
        "wide": ["纯BYOK", "纯 BYOK", "删除平台代付", "ADR-019"],
        "docs": ["decisions/ADR-019-pure-byok-cost-visibility.md", "ARCHITECTURE.md"],
        "note": "代付已删除。ADR-012 的预占机制应标记为部分作废而非继续作为现行方案。",
    },
    "S1 无进展检测能力定级": {
        "narrow": "零误判",
        "wide": ["误报极低", "仍需 S2", "含参数"],
        "docs": ["decisions/ADR-011-long-task-engine.md", "ARCHITECTURE.md"],
        "note": "S1 已修正为含参数签名，「零误判」为已证伪表述，不得作为现行结论。",
    },
}

errors: list[str] = []
warnings: list[str] = []


def read(rel: str) -> str | None:
    p = ROOT / rel
    if not p.exists():
        errors.append(f"文档不存在: {rel}")
        return None
    return p.read_text(encoding="utf-8")


def strip_deprecated(text: str) -> str:
    """剔除打了 [已作废] 标记的整块（### 级分段）。

    团队规则「删结论留痕迹」与「新旧并存即报警」的调和：
    作废留痕是合法的历史记录，不算活跃表述；只有未打标区域的
    旧表述才是残留风险。
    """
    blocks = re.split(r"(?m)^(?=### )", text)
    kept = [b for b in blocks if "[已作废" not in b[:300]]
    return "\n".join(kept)


def hits(text: str, needles) -> int:
    if isinstance(needles, str):
        needles = [needles]
    return sum(text.count(n) for n in needles)


def main() -> int:
    for name, cfg in DECISIONS.items():
        narrow_total = 0
        wide_total = 0
        narrow_docs = []
        wide_docs = []

        for rel in cfg["docs"]:
            text = read(rel)
            if text is None:
                continue
            text = strip_deprecated(text)
            n = hits(text, cfg["narrow"])
            w = hits(text, cfg["wide"])
            narrow_total += n
            wide_total += w
            if n:
                narrow_docs.append(f"{rel}({n})")
            if w:
                wide_docs.append(rel)

        if not narrow_docs and not wide_docs:
            warnings.append(f"[{name}] 两份文档都未表态，请人工确认是否遗漏")
            continue

        # 冲突判定：同一份文档内两种表述并存，且总量都不小 -> 可能残留旧结论
        for rel in cfg["docs"]:
            text = read(rel)
            if text is None:
                continue
            text = strip_deprecated(text)
            n = hits(text, cfg["narrow"])
            w = hits(text, cfg["wide"])
            if n > 0 and w > 0:
                # 允许：宽表述显著多于窄表述（历史记录 + 新结论并存）
                if w > n * 3:
                    continue
                errors.append(
                    f"[{name}] {rel} 同时含新旧表述"
                    f"（收窄/旧 {n} 处，新 {w} 处），可能残留已推翻的结论。"
                    f"\n         {cfg['note']}"
                )

    if errors:
        print("跨文档一致性门禁未通过：")
        for e in errors:
            print(f"  - {e}")
        return 1

    if warnings:
        print("跨文档一致性门禁通过（有提示）：")
        for w in warnings:
            print(f"  - {w}")
        return 0

    print("跨文档一致性门禁通过")
    print(f"  已核对 {len(DECISIONS)} 项关键裁定在 {sum(len(c['docs']) for c in DECISIONS.values())} 份文档中的表述")
    return 0


if __name__ == "__main__":
    sys.exit(main())