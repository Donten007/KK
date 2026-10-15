"""阻断级：AC-17 五条误杀测试（SPEC §9.1 / ADR-016）。

优先级：**前三条「不许误杀」不低于后两条「必须能杀」**——熔断误报率高的系统
比没有熔断更糟，用户会失去信任并直接关掉功能。

 ① 下载 50 个竞品页面（url 递增）→ 全程不熔断
 ② 逐行处理 100 条 Excel 记录（index 递增）→ 全程不熔断
 ③ 批量调用同一接口 30 次（id 递增）→ 全程不熔断
    **且必须能证明修正前后的行为差异**：仅含 tool_name 的旧签名跑同一任务应当误杀
 ④ 原地重试同一失败 URL → 第 5 次熔断
 ⑤ 参数固定的死循环 → 第 5 次熔断

判定入口统一用 progress_guard.evaluate（与生产同一条路径，不用测试专用分支）。
"""

from __future__ import annotations

import pytest
from app.agents.progress_guard import (
    IDENTICAL_LIMIT,
    MAX_SOFT_PAUSES,
    ProgressState,
    ProgressVerdict,
    evaluate,
)
from app.agents.signature import legacy_tool_signature, tool_signature

pytestmark = pytest.mark.blocking

# 岗位级阈值（竞品监控日报 expected_idle_steps=5）→ 软 5 / 硬 10
IDLE = 5


def run_steps(
    steps: list[tuple[str, dict]], *, idle: int = IDLE, has_executor: bool = True
) -> list[ProgressVerdict]:
    """按顺序推进检测窗口，返回每步判定。"""
    state = ProgressState()
    verdicts: list[ProgressVerdict] = []
    for ordinal, (tool, args) in enumerate(steps, start=1):
        verdict = evaluate(
            state=state,
            signature=tool_signature(tool, args) if tool else None,
            delta_artifacts=1,  # 每步都有产出（S2 不断链）
            expected_idle_steps=idle,
            current_ordinal=ordinal,
            has_executor=has_executor,
        )
        verdicts.append(verdict)
        state = verdict.next_state
    return verdicts


def first_circuit_index(verdicts: list[ProgressVerdict]) -> int | None:
    for i, v in enumerate(verdicts, start=1):
        if v.level == "circuit_break":
            return i
    return None


# ---- 用例 ①：下载 50 个页面（url 递增）全程不熔断 ----


def test_fetch_50_pages_with_incrementing_urls_never_trips() -> None:
    steps = [("fetch_url", {"url": f"https://competitor{i}.example.com/pricing"}) for i in range(50)]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) is None, "合法的批量抓取被误判为死循环"


# ---- 用例 ②：逐行处理 100 条记录（index 递增）全程不熔断 ----


def test_process_100_rows_with_incrementing_index_never_trips() -> None:
    steps = [("read_row", {"index": i, "table": "orders"}) for i in range(100)]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) is None


# ---- 用例 ③：同一接口 30 次（id 递增）不熔断，且旧签名会误杀 ----


def test_batch_same_endpoint_with_incrementing_id_never_trips() -> None:
    steps = [("fetch_record", {"id": 1000 + i}) for i in range(30)]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) is None, "id 递增的批量调用被误判为死循环"


def test_case3_proves_before_after_difference() -> None:
    """用例 ③ 的区分力证明：旧签名（仅 tool_name）跑同一任务**必须**误杀。

    若旧签名也不误杀，说明该测试无区分力——测了也白测（AC-17 明确要求）。
    """
    steps = [("fetch_record", {"id": 1000 + i}) for i in range(30)]
    # 旧签名：参数被丢弃 → 30 步签名完全相同 → 第 5 次必然熔断
    legacy_state = ProgressState()
    legacy_circuit_at = None
    for ordinal in range(1, len(steps) + 1):
        tool, _args = steps[ordinal - 1]
        verdict = evaluate(
            state=legacy_state,
            signature=legacy_tool_signature(tool),
            delta_artifacts=1,
            expected_idle_steps=IDLE,
            current_ordinal=ordinal,
        )
        legacy_state = verdict.next_state
        if verdict.level == "circuit_break":
            legacy_circuit_at = ordinal
            break
    assert legacy_circuit_at == IDENTICAL_LIMIT, (
        f"旧签名应在第 {IDENTICAL_LIMIT} 次熔断（证明新签名修正了误杀），"
        f"实际 {legacy_circuit_at}"
    )


# ---- 用例 ④：原地重试同一失败 URL → 第 5 次熔断 ----


def test_retry_same_failing_url_circuits_on_fifth() -> None:
    steps = [("fetch_url", {"url": "https://broken.example.com/api"}) for _ in range(8)]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) == IDENTICAL_LIMIT, (
        f"原地重试同一 URL 应在第 {IDENTICAL_LIMIT} 次熔断，实际 {first_circuit_index(verdicts)}"
    )


# ---- 用例 ⑤：参数固定的死循环 → 第 5 次熔断 ----


def test_fixed_argument_deadloop_circuits_on_fifth() -> None:
    steps = [("render_sheet", {"query": "SELECT 1", "format": "xlsx"}) for _ in range(10)]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) == IDENTICAL_LIMIT


def test_circuit_message_never_exposes_system_behaviour() -> None:
    """熔断文案只讲业务事实（AC-F3 / 坑 12）：禁止出现阈值、检测、重复调用模式。"""
    steps = [("fetch_url", {"url": "https://x.example.com"}) for _ in range(6)]
    verdicts = run_steps(steps)
    circuit = next(v for v in verdicts if v.level == "circuit_break")
    banned = ["阈值", "检测", "重复调用", "无进展", "circuit", "trigger", "window"]
    for word in banned:
        assert word not in circuit.user_message, f"熔断文案暴露了系统行为：{circuit.user_message}"
    assert circuit.user_message  # 业务文案不能为空


# ---- 周期循环（fetch→parse 交替，参数不变）也应被抓住 ----


def test_alternating_cycle_is_caught() -> None:
    """周期 2 的循环：窗口哈希重复即熔断（不是死循环，也是在原地打转）。"""
    steps = [
        ("fetch_url", {"url": "https://a.example.com"}) if i % 2 == 0
        else ("parse_html", {"url": "https://a.example.com"})
        for i in range(12)
    ]
    verdicts = run_steps(steps)
    assert first_circuit_index(verdicts) is not None, "交替循环未被抓住"


# ---- S2：产出物无增量的空转 ----


def test_s2_trips_on_idle_artifacts() -> None:
    """S2 是第二道防线：工具不同（签名不重复）但产出物连续无增量 → 硬熔断。"""
    state = ProgressState()
    verdict = None
    for ordinal in range(1, IDLE * 2 + 2):
        verdict = evaluate(
            state=state,
            signature=tool_signature("summarize", {"page": ordinal}),  # 签名每次不同
            delta_artifacts=0,  # 但没有新产出物
            expected_idle_steps=IDLE,
            current_ordinal=ordinal,
        )
        state = verdict.next_state
        if verdict.level == "circuit_break":
            break
    assert verdict is not None and verdict.level == "circuit_break"
    assert verdict.reason == "no_new_artifacts"


def test_s2_soft_pause_before_hard_break() -> None:
    """软阈值先拉人确认（不熔断），达到上限后不再问（MAX_SOFT_PAUSES）。"""
    state = ProgressState()
    pauses = 0
    for ordinal in range(1, IDLE * 2 + 3):
        verdict = evaluate(
            state=state,
            signature=tool_signature("summarize", {"page": ordinal}),
            delta_artifacts=0,
            expected_idle_steps=IDLE,
            current_ordinal=ordinal,
        )
        state = verdict.next_state
        if verdict.level == "soft_pause":
            pauses += 1
        if verdict.level == "circuit_break":
            break
    assert pauses == MAX_SOFT_PAUSES, f"软暂停次数应上限 {MAX_SOFT_PAUSES}，实际 {pauses}"


# ---- 阈值由岗位控制而非硬编码（ADR-011 Verification 用例 10）----


def test_threshold_follows_job_template_parameter() -> None:
    """同一条检测逻辑，用 expected_idle_steps=5 与 =20 跑，熔断步数必须不同。"""
    def run_idle(idle: int) -> int | None:
        state = ProgressState()
        for ordinal in range(1, 60):
            v = evaluate(
                state=state,
                signature=tool_signature("summarize", {"page": ordinal}),
                delta_artifacts=0,
                expected_idle_steps=idle,
                current_ordinal=ordinal,
                has_executor=False,
            )
            state = v.next_state
            if v.level == "circuit_break":
                return ordinal
        return None

    assert run_idle(5) == 10  # 硬阈值 = 岗位预期 × 2
    assert run_idle(20) == 40  # 阈值随岗位参数线性变化，证明未硬编码