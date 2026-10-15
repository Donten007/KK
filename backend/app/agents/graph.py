"""LangGraph 图定义与执行骨架（ADR-011 三层模型的 L2 层）。

【需资深】三条不可违背的设计约束（SPEC §4.6 F6-1/F6-4/F6-5）：
- F6-4：thread_id 必须等于 goal_id，否则用户刷新页面找不到自己的任务
- F6-5：**LLM 调用必须在图节点内部**。LangGraph 的重放语义是「已完成节点不重跑」，
  图外的循环会被重放并重复计费
- 熔断判定在节点入口（**下次 LLM 调用之前**），不在出口

图的形状（竞品监控日报岗位的通用骨架）：
    START → step_1 → step_2 → ... → step_N → END
每个节点 = 「熔断判定 → 工具调用 + 可选 LLM → 业务落库」。每步独立 checkpoint，
断点续跑能精确到步（AC-4「从第 26 步执行」）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from app.agents.progress_guard import ProgressVerdict
from app.agents.runtime_context import (
    current_cancel_event,
    reset_graph_context,
    set_graph_context,
)
from langgraph.graph import END, START, StateGraph


@dataclass
class StepSpec:
    """一个业务步骤的声明（来自岗位模板 steps_def）。

    expected_artifacts / artifact_kind / artifact_hash 用于 S2 产出物增量判定：
    步骤声明产出什么内容，哈希相同即「改了又改回原样」，不计增量（ADR-011）。
    """

    ordinal: int
    title: str  # 业务语言，禁用 Agent/节点/token 术语
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    needs_llm: bool = False
    expected_artifacts: int = 1
    artifact_kind: str = "record"
    artifact_hash: str = ""
    node_name: str = ""

    def __post_init__(self) -> None:
        # 节点名与序号绑定：断点续跑靠它定位到具体步骤（AC-4）
        self.node_name = f"step_{self.ordinal}"


@dataclass
class StepOutcome:
    """步骤执行结果。"""

    output_ref: str | None = None
    cost_cents: int = 0
    model_id: str | None = None
    artifact_ids: list[uuid.UUID] = field(default_factory=list)
    error_code: str | None = None
    status: str = "succeeded"  # succeeded / failed / skipped


@dataclass
class GraphContext:
    """传给步骤执行器的上下文。"""

    goal_id: uuid.UUID
    tenant_id: uuid.UUID
    step: StepSpec
    attempt: int


@dataclass
class GoalState:
    """LangGraph 状态。只放可序列化的图状态（checkpoint 落 PG）。"""

    ordinal: int = 0
    total_steps: int = 0
    delta_artifacts: int = 0
    spent_cents: int = 0
    last_output: str | None = None
    status: str = "running"


StepExecutor = Callable[[GraphContext], Awaitable[StepOutcome]]
# 步骤完成回调：负责落 task_steps、登记产出物、推进检测窗口
# （必须在 checkpoint 之前执行，SPEC 坑 3）
StepFinishedHook = Callable[[StepSpec, GoalState, StepOutcome], Awaitable[None]]


class CircuitBreakSignal(Exception):
    """熔断信号。抛出后整图停止，已完成步骤保留（AC-5）。计失败，不进 TCR 分子。"""

    def __init__(self, reason: str, user_message: str) -> None:
        self.reason = reason
        self.user_message = user_message
        super().__init__(reason)


class SoftPauseSignal(Exception):
    """软暂停信号（拉人确认，ADR-011 §2）。"""

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        super().__init__(user_message)


class GoalCancelled(Exception):
    """协作式取消（步骤边界收到取消信号）。"""


def build_graph(
    *,
    goal_id: uuid.UUID,
    tenant_id: uuid.UUID,
    steps: list[StepSpec],
    executor: StepExecutor,
    guard: Callable[[StepSpec, GoalState], Awaitable[ProgressVerdict]],
    on_step_finished: StepFinishedHook,
    checkpointer: Any | None = None,
) -> Any:
    """构造 LangGraph 编译产物。

    节点内的顺序（不可调换）：
      1. 检查取消信号（协作式取消，ADR-017 步骤 3）
      2. 无进展判定 → circuit_break 直接抛出（**不再调 LLM**，不产生熔断后费用）
      3. 真正执行步骤（工具 + 可选 LLM，F6-5）
      4. 回调落库（task_steps / artifacts / 检测窗口）→ 返回后 LangGraph 才落 checkpoint

    步骤用静态线性链展开：MVP 岗位步骤数 3-8（SPEC §2.4），动态跳转留给 Phase 3。
    """
    graph = StateGraph(GoalState)

    for step in steps:
        _add_step_node(
            graph, goal_id=goal_id, tenant_id=tenant_id, step=step,
            executor=executor, guard=guard, on_step_finished=on_step_finished,
        )

    graph.add_edge(START, steps[0].node_name)
    for prev, nxt in pairwise(steps):
        graph.add_edge(prev.node_name, nxt.node_name)
    graph.add_edge(steps[-1].node_name, END)
    # checkpointer 传入即启用断点续跑（AC-4）；None 时只能单次跑通
    return graph.compile(checkpointer=checkpointer)


def _add_step_node(
    graph: StateGraph[GoalState, Any, GoalState, GoalState],
    *,
    goal_id: uuid.UUID,
    tenant_id: uuid.UUID,
    step: StepSpec,
    executor: StepExecutor,
    guard: Callable[[StepSpec, GoalState], Awaitable[ProgressVerdict]],
    on_step_finished: StepFinishedHook,
) -> None:
    async def node(state: GoalState) -> dict[str, Any]:
        # 1) 协作式取消：在步骤边界检查（ADR-017 步骤 3）
        event = current_cancel_event()
        if event is not None and event.is_set():
            raise GoalCancelled(f"goal cancelled at step {step.ordinal}")

        # 2) 无进展判定 —— 必须在 LLM 调用之前（SPEC §4.6）
        verdict = await guard(step, state)
        if verdict.level == "circuit_break":
            raise CircuitBreakSignal(verdict.reason, verdict.user_message)
        if verdict.level == "soft_pause":
            raise SoftPauseSignal(verdict.user_message)

        # 3) 真正执行（LLM 调用在节点内部，F6-5）
        ctx = GraphContext(
            goal_id=goal_id, tenant_id=tenant_id, step=step, attempt=state.ordinal + 1
        )
        token = set_graph_context(ctx)
        try:
            outcome = await executor(ctx)
        finally:
            reset_graph_context(token)

        # 4) 业务落库（在 checkpoint 之前）
        await on_step_finished(step, state, outcome)

        return {
            "ordinal": step.ordinal,
            "delta_artifacts": len(outcome.artifact_ids),
            "spent_cents": state.spent_cents + outcome.cost_cents,
            "last_output": outcome.output_ref,
            "status": outcome.status,
        }

    node.__name__ = step.node_name
    graph.add_node(step.node_name, node)