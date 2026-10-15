"""Goal 执行器：LangGraph 运行 + 业务步骤落库 + 协作式取消（SPEC §4.6）。

三条设计约束的落地：
- F6-1 幂等：业务写入用 ON CONFLICT DO NOTHING + PK (goal_id, step_ordinal)；
  checkpoint 与业务数据**不在同一事务**（LangGraph 的既成事实，
  所以幂等是唯一防线，SPEC 坑 3）
- F6-4 thread_id == goal_id
- F6-5 LLM 调用在节点内部（由 graph.py 保证）

断点续跑：崩溃后用同一 thread_id 重新 ainvoke，LangGraph 从最后 checkpoint
继续，**已完成节点不重跑** → 不重复计费（AC-4）。

【实习生可做】新增岗位只需补 steps_def 声明，不用改本文件。
【需资深】改动本文件任何一处之前，先读 SPEC §4.6 与 ADR-011。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from app.agents.cancellation import CancelRegistry
from app.agents.graph import (
    CircuitBreakSignal,
    GoalCancelled,
    GoalState,
    SoftPauseSignal,
    StepExecutor,
    StepOutcome,
    StepSpec,
    build_graph,
)
from app.agents.progress_guard import ProgressState, ProgressVerdict, evaluate
from app.agents.runtime_context import set_cancel_event
from app.agents.signature import tool_signature
from app.agents.status_transitions import StatusTransitions
from app.core.logging import get_logger
from app.db.rls import tenant_transaction
from app.repositories.event_repo import (
    GoalProgressRepository,
    TaskArtifactRepository,
)
from app.repositories.goal_repo import GoalRepository
from app.repositories.step_repo import TaskStepRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("runner")


class GoalRunResult:
    """一次运行的结果。runner 内部流转，不直接进 HTTP 响应。"""

    def __init__(self, status: str, *, reason: str = "", user_message: str = "") -> None:
        self.status = status  # completed / failed / cancelled / waiting_approval
        self.reason = reason
        self.user_message = user_message

    def __repr__(self) -> str:
        return f"<GoalRunResult {self.status} reason={self.reason}>"


class GoalRunner:
    """执行单个 goal：图构建与业务落库的编排点。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        tenant_id: uuid.UUID,
        registry: CancelRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self.registry = registry

    async def run(
        self,
        *,
        goal_id: uuid.UUID,
        steps: list[StepSpec],
        executor: StepExecutor,
        expected_idle_steps: int,
        checkpointer: Any,
        input_state: dict[str, Any] | None = None,
    ) -> GoalRunResult:
        """执行或续跑一个 goal。续跑与首次跑同一条路径——
        LangGraph 依据 checkpoint 自动从断点继续（AC-4）。"""
        handle = await self.registry.register(goal_id)
        cancel_token = set_cancel_event(handle.cancel_event)
        try:
            return await self._run_inner(
                goal_id=goal_id,
                steps=steps,
                executor=executor,
                expected_idle_steps=expected_idle_steps,
                checkpointer=checkpointer,
                input_state=input_state or {},
            )
        finally:
            await self.registry.unregister(goal_id)
            set_cancel_event(None)
            del cancel_token

    async def _run_inner(
        self,
        *,
        goal_id: uuid.UUID,
        steps: list[StepSpec],
        executor: StepExecutor,
        expected_idle_steps: int,
        checkpointer: Any,
        input_state: dict[str, Any],
    ) -> GoalRunResult:
        progress = await self._load_progress(goal_id)

        async def guard(step: StepSpec, _state: GoalState) -> ProgressVerdict:
            """无进展判定：S1a（签名含归一化参数）+ S2（产出物增量）。"""
            nonlocal progress  # 无它则 progress 只在 guard 局部生效，窗口永不推进
            signature = tool_signature(step.tool_name, step.tool_args) if step.tool_name else None
            verdict = evaluate(
                state=progress,
                signature=signature,
                delta_artifacts=step.expected_artifacts,
                expected_idle_steps=expected_idle_steps,
                current_ordinal=step.ordinal,
            )
            progress = verdict.next_state
            return verdict

        async def on_step_finished(
            step: StepSpec, _state: GoalState, outcome: StepOutcome
        ) -> None:
            # 业务写入 → 检测窗口落盘 → 返回后 LangGraph 才落 checkpoint。
            # 顺序不可颠倒：checkpoint 先行会重跑已完成节点并重复计费（坑 3）
            await self._persist_step(goal_id=goal_id, step=step, outcome=outcome)
            await self._persist_progress(goal_id, progress)

        compiled = build_graph(
            goal_id=goal_id,
            tenant_id=self._tenant_id,
            steps=steps,
            executor=executor,
            guard=guard,
            on_step_finished=on_step_finished,
            checkpointer=checkpointer,
        )

        # F6-4：thread_id 必须等于 goal_id
        config = {"configurable": {"thread_id": str(goal_id)}}

        try:
            await self._transition(goal_id, StatusTransitions.set_running)
            payload = await self._initial_payload(compiled, config, steps, goal_id)
            await compiled.ainvoke(payload, config=config)
        except CircuitBreakSignal as exc:
            # 用 partial 而不是 lambda 闭包捕获 exc：except 结束即删除异常变量，
            # 闭包虽在此处调用没问题，但写法脆弱且会被静态检查判为 F821
            await self._transition(
                goal_id,
                partial(
                    StatusTransitions.set_circuit_break,
                    reason=exc.reason,
                    user_message=exc.user_message,
                ),
            )
            return GoalRunResult("failed", reason=exc.reason, user_message=exc.user_message)
        except SoftPauseSignal as exc:
            await self._transition(
                goal_id,
                partial(
                    StatusTransitions.set_soft_pause,
                    user_message=exc.user_message,
                    step_title=exc.step_title,
                    step_ordinal=exc.step_ordinal,
                ),
            )
            return GoalRunResult(
                "waiting_approval", reason="soft_pause", user_message=exc.user_message
            )
        except GoalCancelled:
            await self._transition(goal_id, StatusTransitions.set_cancelled)
            return GoalRunResult("cancelled", reason="user_cancel")
        except Exception as exc:  # 任何未预期异常都要落 failed，不能让 run 永久 running
            logger.exception(
                "goal_run_failed", goal_id=str(goal_id), error_type=type(exc).__name__
            )
            await self._transition(
                goal_id, partial(StatusTransitions.set_failed, error_code="internal_error")
            )
            return GoalRunResult("failed", reason="internal_error")

        await self._transition(goal_id, StatusTransitions.set_completed)
        return GoalRunResult("completed")

    async def _transition(
        self, goal_id: uuid.UUID, action: Callable[[StatusTransitions, uuid.UUID], Awaitable[None]]
    ) -> None:
        """在独立事务里执行状态收敛（每个终态一次提交，互不牵连）。"""
        async with self._new_session() as session, tenant_transaction(session, self._tenant_id):
            await action(StatusTransitions(session, self._tenant_id), goal_id)

    # ---- 断点续跑判定 ----

    async def _initial_payload(
        self, compiled: Any, config: dict[str, Any], steps: list[StepSpec], goal_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """已有 checkpoint → 传 None 让 LangGraph 从断点继续；否则传初始状态。

        【需资深】这是断点续跑最容易做错的一处（本次实测踩到）：
        对已存在的 thread 再传非空 input，LangGraph 会**开启一次全新的 run
        从头执行**，已完成节点被重跑 → LLM 重复调用 → 重复计费（直接违反 AC-4）。
        续跑的正确姿势是 `ainvoke(None, config)`。

        snapshot kind 校验：checkpoint 的 thread_id 必须与当前 goal 一致。
        thread_id 由服务端从租户隔离的 goal 行派生（F6-4），此校验是纵深防御
        —— 防止未来任何代码路径把错配的 config 传进来造成跨任务状态污染。
        """
        snapshot = await compiled.aget_state(config)
        if snapshot.values:
            snap_thread = snapshot.config["configurable"]["thread_id"]
            if snap_thread != str(goal_id):
                logger.error(
                    "checkpoint_kind_mismatch",
                    expected=str(goal_id),
                    found=snap_thread,
                )
                raise RuntimeError(
                    f"checkpoint 快照与任务不匹配（thread={snap_thread}, goal={goal_id}）"
                )
            logger.info(
                "goal_resuming_from_checkpoint",
                goal_id=snap_thread,
                completed_nodes=snapshot.values.get("ordinal"),
            )
            return None
        return {"total_steps": len(steps)}

    def _new_session(self) -> AsyncSession:
        """每次状态写入用独立会话：runner 与请求共享会话会放大回滚半径。"""
        return self._session_factory()

    # ---- 检测窗口（必须落盘）----

    async def _load_progress(self, goal_id: uuid.UUID) -> ProgressState:
        async with self._new_session() as session, tenant_transaction(session, self._tenant_id):
            repo = GoalProgressRepository(session)
            row = await repo.load(tenant_id=self._tenant_id, goal_id=goal_id)
            return ProgressState.from_row(row)

    async def _persist_progress(self, goal_id: uuid.UUID, state: ProgressState) -> None:
        async with self._new_session() as session, tenant_transaction(session, self._tenant_id):
            repo = GoalProgressRepository(session)
            await repo.save(tenant_id=self._tenant_id, goal_id=goal_id, state=state.to_json())

    # ---- 业务落库（幂等）----

    async def _persist_step(
        self, *, goal_id: uuid.UUID, step: StepSpec, outcome: StepOutcome
    ) -> None:
        async with self._new_session() as session, tenant_transaction(session, self._tenant_id):
            steps_repo = TaskStepRepository(session)
            artifact_repo = TaskArtifactRepository(session)
            goal_repo = GoalRepository(session)

            existing = await steps_repo.get(
                tenant_id=self._tenant_id, goal_id=goal_id, ordinal=step.ordinal
            )
            if existing is None:
                await steps_repo.upsert_running(
                    tenant_id=self._tenant_id, goal_id=goal_id, ordinal=step.ordinal, title=step.title
                )
            # 幂等核心：已 succeeded 的步骤不再累计成本（AC-4「不重复计费」）
            already_done = existing is not None and existing.status == "succeeded"

            delta = 0
            if not already_done:
                for artifact_id in outcome.artifact_ids:
                    is_new = await artifact_repo.record(
                        tenant_id=self._tenant_id,
                        goal_id=goal_id,
                        artifact_id=artifact_id,
                        step_ordinal=step.ordinal,
                        kind=step.artifact_kind,
                        content_hash=step.artifact_hash,
                    )
                    if is_new:
                        delta += 1

                await steps_repo.finish(
                    tenant_id=self._tenant_id,
                    goal_id=goal_id,
                    ordinal=step.ordinal,
                    status=outcome.status,
                    output_ref=outcome.output_ref,
                    cost_cents=0 if already_done else outcome.cost_cents,
                    model_id=outcome.model_id,
                    tool_name=step.tool_name,
                    tool_signature=tool_signature(step.tool_name, step.tool_args)
                    if step.tool_name
                    else None,
                    delta_artifacts=delta,
                    error_code=outcome.error_code,
                )
                if outcome.cost_cents and not already_done:
                    await goal_repo.add_spent(
                        tenant_id=self._tenant_id, goal_id=goal_id, cost_cents=outcome.cost_cents
                    )

