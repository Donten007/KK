"""S1a + S2 双信号无进展检测（ADR-011 §2 / SPEC §4.6 / ADR-016）。

【需资深】为什么必须是双信号，而不是单 S1：
S1a 收窄（签名含参数摘要）后仍是非零误判率——它是工程判断不是数学证明。
F6-lite 用 S2（产出物增量）作第二道防线：S1a 抓「同签名重复序列」，
S2 抓「反复重写同一份文件、artifact 数涨但内容没变」的空转。

判定时机：必须在**下一次 LLM 调用之前**（SPEC §4.6）。死循环场景下每轮都是
完整 LLM 调用，等模型返回再判定等于白烧钱。

检测窗口状态（recent_signatures / seen_tool_windows / idle_streak）随每步落盘
（goal_progress_state 表），否则崩溃重启归零，死循环要重复触发 N 次才熔断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.signature import signature_streak, tool_signature, window_hash

# S1a 窗口长度：ADR-011 §2 取 K=5（AC-17 前三条用例都在第 5 步附近给出边界）
S1A_WINDOW = 5
# 静态死循环：末尾连续 N 次完全相同签名即熔断（AC-17 用例 ④⑤）
IDENTICAL_LIMIT = 5
# 软暂停次数上限：防止无限问（ADR-011 §2）
MAX_SOFT_PAUSES = 2


@dataclass
class ProgressState:
    """检测窗口状态（落盘到 goal_progress_state）。"""

    recent_signatures: list[str] = field(default_factory=list)
    seen_tool_windows: list[str] = field(default_factory=list)
    idle_streak: int = 0
    identical_signature_streak: int = 0
    soft_pause_count: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "recent_signatures": list(self.recent_signatures),
            "seen_tool_windows": list(self.seen_tool_windows),
            "idle_streak": self.idle_streak,
            "identical_signature_streak": self.identical_signature_streak,
            "soft_pause_count": self.soft_pause_count,
        }

    @classmethod
    def from_row(cls, row: Any) -> ProgressState:
        if row is None:
            return cls()
        return cls(
            recent_signatures=list(row.recent_signatures or []),
            seen_tool_windows=list(row.seen_tool_windows or []),
            idle_streak=row.idle_streak or 0,
            identical_signature_streak=row.identical_signature_streak or 0,
            soft_pause_count=row.soft_pause_count or 0,
        )


@dataclass(frozen=True)
class ProgressVerdict:
    """判定结果。

    level:
      ok           —— 继续
      soft_pause   —— 拉人确认（interrupt），不熔断
      circuit_break—— 停止，保留已完成成果，计失败（不进 TCR 分子）
    reason: 机器可读，进审计/admin 可见
    user_message: **业务语言**，进「我停下来过」板块；
                  禁止出现「阈值/检测到/重复调用模式」等系统行为词（AC-F3 / 坑 12）
    """

    level: str
    reason: str
    user_message: str
    next_state: ProgressState


def _next_state(state: ProgressState, signature: str | None, delta_artifacts: int) -> ProgressState:
    """推进检测窗口。签名与产出物增量都要计入，否则漏检。"""
    recent = list(state.recent_signatures)
    if signature is not None:
        recent.append(signature)
        # 只保留最近 S1A_WINDOW 条（够构成窗口即可，避免 JSONB 无限增长）
        recent = recent[-S1A_WINDOW:]
    if delta_artifacts > 0:
        return ProgressState(
            recent_signatures=recent,
            seen_tool_windows=list(state.seen_tool_windows),
            idle_streak=0,
            identical_signature_streak=0,
            soft_pause_count=state.soft_pause_count,
        )
    return ProgressState(
        recent_signatures=recent,
        seen_tool_windows=list(state.seen_tool_windows),
        idle_streak=state.idle_streak + 1,
        identical_signature_streak=state.identical_signature_streak,
        soft_pause_count=state.soft_pause_count,
    )


def evaluate(
    *,
    state: ProgressState,
    signature: str | None,
    delta_artifacts: int,
    expected_idle_steps: int,
    current_ordinal: int,
    has_executor: bool = True,
) -> ProgressVerdict:
    """判定本步是否应熔断 / 软暂停 / 继续。

    expected_idle_steps 由岗位模板声明（ADR-011 §3），软阈值 = 岗位预期，
    硬阈值 = 岗位预期 × 2。禁止硬编码。
    """
    next_state = _next_state(state, signature, delta_artifacts)

    # ---- S1a：签名序列重复 ----
    # 静态死循环：末尾连续 IDENTICAL_LIMIT 次相同签名（AC-17 ④⑤，第 5 次熔断）
    if signature is not None:
        streak = signature_streak(next_state.recent_signatures)
        next_state.identical_signature_streak = streak
        if streak >= IDENTICAL_LIMIT:
            return ProgressVerdict(
                "circuit_break",
                "repeated_tool_signature",
                f"我在第 {current_ordinal} 步停下来，前面已经完成的成果都保留着。",
                next_state,
            )
        # 循环序列重复：最近 S1A_WINDOW 条签名构成的窗口此前出现过（周期 2-5 的循环）
        if len(next_state.recent_signatures) >= S1A_WINDOW:
            window = next_state.recent_signatures[-S1A_WINDOW:]
            w_hash = window_hash(window)
            if w_hash in next_state.seen_tool_windows:
                return ProgressVerdict(
                    "circuit_break",
                    "repeated_tool_sequence",
                    f"我在第 {current_ordinal} 步停下来，前面已经完成的成果都保留着。",
                    next_state,
                )
            next_state.seen_tool_windows = [*next_state.seen_tool_windows[-49:], w_hash]

    # ---- S2：产出物无增量 ----
    soft_n = max(1, expected_idle_steps)
    hard_n = soft_n * 2
    if next_state.idle_streak >= hard_n:
        return ProgressVerdict(
            "circuit_break",
            "no_new_artifacts",
            f"我卡在第 {current_ordinal} 步，已经停下。前面的成果都保留着。",
            next_state,
        )
    if (
        next_state.idle_streak >= soft_n
        and has_executor
        and next_state.soft_pause_count < MAX_SOFT_PAUSES
    ):
        paused = ProgressState(
            recent_signatures=list(next_state.recent_signatures),
            seen_tool_windows=list(next_state.seen_tool_windows),
            idle_streak=next_state.idle_streak,
            identical_signature_streak=next_state.identical_signature_streak,
            soft_pause_count=next_state.soft_pause_count + 1,
        )
        return ProgressVerdict(
            "soft_pause",
            "uncertain_progress",
            f"我在第 {current_ordinal} 步有点没底，要我继续还是先停下？",
            paused,
        )

    return ProgressVerdict("ok", "progressing", "", next_state)


def signature_for(tool_name: str, args: dict[str, Any]) -> str:
    """对外暴露的签名计算入口（供步骤执行器使用）。"""
    return tool_signature(tool_name, args)