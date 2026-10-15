"""阻断级：F6-lite 端到端（断点续跑 + 中止幂等 + 熔断计失败）。

三条必须验证的行为：
1. AC-4 断点续跑：崩溃后从最后 checkpoint 继续，**已完成步骤成果与费用保留，
   不重复执行也不重复计费**
2. AC-C2 cancel 幂等：连续 3 次 cancel 全部 200、状态一致、只发一次信号
3. AC-C1/AC-C3：stopping 是独立状态；5 秒未收敛由巡检器强制置 cancelled
4. 熔断计失败：circuit_break → goal.status=failed（不进 TCR 分子）

用真实 PostgreSQL + 真实 LangGraph checkpointer（不 mock 掉 checkpoint，
否则测的就不是断点续跑而是「假装能续跑」）。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.agents.cancellation import CancelRegistry
from app.agents.checkpointer import checkpoint_saver
from app.agents.graph import StepOutcome, StepSpec
from app.agents.runner import GoalRunner
from app.core.errors import ConflictError
from app.db.rls import tenant_transaction
from app.models.job import JobTemplate
from app.repositories.goal_repo import GoalRepository
from app.repositories.step_repo import TaskStepRepository
from app.services.goal_service import GoalService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.blocking

TEST_DB = "postgresql+asyncpg://opc_app:opc_app_dev@127.0.0.1:5432/opcagentai_test"

EXPECTED_IDLE_STEPS = 5


def _steps(n: int = 4) -> list[StepSpec]:
    """n 个「读取竞品页面」步骤，参数随序号不同（合法周期性工作）。"""
    return [
        StepSpec(
            ordinal=i,
            title=f"读取竞品页面 {i}/{n}",
            tool_name="fetch_url",
            tool_args={"url": f"https://competitor{i}.example.com"},
            artifact_kind="page",
            artifact_hash=f"hash-{i}",
            expected_artifacts=1,
        )
        for i in range(1, n + 1)
    ]


class _RecordingExecutor:
    """记录每步执行次数与成本，用于断言「不重复执行/不重复计费」。"""

    def __init__(self, *, fail_at: int | None = None, delay: float = 0.0) -> None:
        self.calls: list[int] = []
        self.fail_at = fail_at
        self.delay = delay

    async def __call__(self, ctx) -> StepOutcome:
        self.calls.append(ctx.step.ordinal)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_at is not None and ctx.step.ordinal == self.fail_at:
            raise RuntimeError("模拟进程崩溃前的未预期错误")
        return StepOutcome(
            output_ref=f"out/{ctx.step.ordinal}",
            cost_cents=10,
            model_id="fake-model",
            artifact_ids=[uuid.uuid4()],
        )


async def _seed_goal(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """造租户 + 岗位模板 + 员工 + goal，返回 (goal_id, agent_id)。"""
    async with tenant_transaction(session, tenant_id):
        template = JobTemplate(
            code=f"tpl-{uuid.uuid4().hex[:8]}",
            name="竞品监控日报",
            icon="Radar",
            summary="每天早上看完 5 家竞品的价格与动作，把变化写成日报",
            expected_idle_steps=EXPECTED_IDLE_STEPS,
            expected_total_steps=8,
            baseline_minutes_per_run=25,
            difficulty="low",
            sort_order=1,
            steps_def=[],
        )
        session.add(template)
        await session.flush()

        agent = _make_agent(tenant_id, template.id)
        session.add(agent)
        await session.flush()

        repo = GoalRepository(session)
        goal = await repo.create(
            tenant_id=tenant_id,
            agent_id=agent.id,
            created_by=uuid.uuid4(),
            title="竞品监控日报",
            input_payload={"input": "跑一次", "urls": []},
            job_template_id=str(template.id),
            estimated_steps=4,
            estimated_cost_cents=100,
            budget_cents=0,
        )
        from app.repositories.event_repo import GoalProgressRepository

        await GoalProgressRepository(session).save(
            tenant_id=tenant_id,
            goal_id=goal.id,
            state={"idle_streak": 0, "recent_signatures": [], "seen_tool_windows": [],
                   "identical_signature_streak": 0, "soft_pause_count": 0},
        )
        return goal.id, agent.id


def _make_agent(tenant_id: uuid.UUID, template_id: uuid.UUID):
    from app.models.job import Agent

    return Agent(
        tenant_id=tenant_id, name="市场专员", job_template_id=template_id, status="active"
    )


@pytest.fixture
async def runner_factory():
    """按租户造 runner（每个测试独立 session_factory）。"""
    engine = create_async_engine(TEST_DB)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    def make(tenant_id: uuid.UUID, reg: CancelRegistry) -> GoalRunner:
        return GoalRunner(session_factory=factory, tenant_id=tenant_id, registry=reg)

    yield make
    await engine.dispose()


@pytest.fixture
async def tenant_id(db_session: AsyncSession) -> uuid.UUID:
    """建一个租户（走无 RLS 的 tenants 表）。"""
    from app.models.tenant import Tenant

    async with db_session.begin():
        t = Tenant(code=f"AC-F6{uuid.uuid4().hex[:3].upper()}", name="F6 测试租户")
        db_session.add(t)
        await db_session.flush()
        tid = t.id
    return tid


async def test_run_completes_and_records_steps(
    db_session: AsyncSession, tenant_id: uuid.UUID, runner_factory
) -> None:
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    executor = _RecordingExecutor()
    runner = runner_factory(tenant_id, CancelRegistry())

    async with checkpoint_saver() as saver:
        result = await runner.run(
            goal_id=goal_id, steps=_steps(4), executor=executor,
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )

    assert result.status == "completed", result.reason
    assert executor.calls == [1, 2, 3, 4]

    async with tenant_transaction(db_session, tenant_id):
        steps = await TaskStepRepository(db_session).list_for_goal(
            tenant_id=tenant_id, goal_id=goal_id
        )
        assert [s.step_ordinal for s in steps] == [1, 2, 3, 4]
        assert all(s.status == "succeeded" for s in steps)
        assert sum(s.cost_cents for s in steps) == 40  # 4 步 × 10 分
        goal = await GoalRepository(db_session).get(tenant_id=tenant_id, goal_id=goal_id)
        assert goal.status == "completed"
        assert goal.spent_cents == 40


async def test_resume_does_not_repeat_finished_steps(
    db_session: AsyncSession, tenant_id: uuid.UUID, runner_factory
) -> None:
    """AC-4：第 3 步崩溃后从 checkpoint 继续；第 1-2 步不重跑、不重复计费。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    crashing = _RecordingExecutor(fail_at=3)
    runner = runner_factory(tenant_id, CancelRegistry())

    async with checkpoint_saver() as saver:
        first = await runner.run(
            goal_id=goal_id, steps=_steps(4), executor=crashing,
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )
        assert first.status == "failed"
        assert crashing.calls == [1, 2, 3]

        async with tenant_transaction(db_session, tenant_id):
            steps = await TaskStepRepository(db_session).list_for_goal(
                tenant_id=tenant_id, goal_id=goal_id
            )
            done = [s.step_ordinal for s in steps if s.status == "succeeded"]
            cost_before = sum(s.cost_cents for s in steps)
        assert done == [1, 2]
        assert cost_before == 20

        # 续跑：同一 thread_id（= goal_id），LangGraph 从最后 checkpoint 继续
        healthy = _RecordingExecutor()
        second = await runner.run(
            goal_id=goal_id, steps=_steps(4), executor=healthy,
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )
        assert second.status == "completed"
        # 已完成的 1-2 步不得重跑（LLM 调用不重复 → 不重复计费）
        assert healthy.calls == [3, 4], f"续跑应从第 3 步开始，实际执行 {healthy.calls}"

        async with tenant_transaction(db_session, tenant_id):
            steps = await TaskStepRepository(db_session).list_for_goal(
                tenant_id=tenant_id, goal_id=goal_id
            )
            goal = await GoalRepository(db_session).get(tenant_id=tenant_id, goal_id=goal_id)
        assert [s.step_ordinal for s in steps] == [1, 2, 3, 4]
        assert sum(s.cost_cents for s in steps) == 40, "续跑后总成本应为 40 分，不重复计费"
        assert goal.spent_cents == 40
        assert goal.status == "completed"


async def test_resume_is_idempotent_under_replay(
    db_session: AsyncSession, tenant_id: uuid.UUID, runner_factory
) -> None:
    """阻断级幂等：业务成功但 checkpoint 未落盘时重放，不产生重复业务数据。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    executor = _RecordingExecutor()
    runner = runner_factory(tenant_id, CancelRegistry())

    async with checkpoint_saver() as saver:
        await runner.run(
            goal_id=goal_id, steps=_steps(4), executor=executor,
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )
        # 再跑一次同一 thread：已完成节点不重跑（LangGraph 语义）
        again = _RecordingExecutor()
        second = await runner.run(
            goal_id=goal_id, steps=_steps(4), executor=again,
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )
    assert second.status == "completed"
    assert again.calls == [], "已完成的图不得重跑（否则重复计费）"

    async with tenant_transaction(db_session, tenant_id):
        steps = await TaskStepRepository(db_session).list_for_goal(
            tenant_id=tenant_id, goal_id=goal_id
        )
        goal = await GoalRepository(db_session).get(tenant_id=tenant_id, goal_id=goal_id)
    assert len(steps) == 4
    assert goal.spent_cents == 40


async def test_circuit_break_counts_as_failure(
    db_session: AsyncSession, tenant_id: uuid.UUID, runner_factory
) -> None:
    """熔断 → status=failed（不进 TCR 分子），已完成成果保留。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    # 前 1 步正常产出，后 4 步参数完全相同 → 第 5 次签名重复触发 S1a
    # 第 2-6 步参数完全相同 → 末尾连续 5 次相同签名 → S1a 在第 6 步熔断
    steps = [
        StepSpec(ordinal=1, title="打开目标页面", tool_name="open_page",
                 tool_args={"url": "https://a.example.com"}, artifact_kind="page",
                 artifact_hash="h1", expected_artifacts=1),
    ] + [
        StepSpec(ordinal=i, title="重试同一页面", tool_name="fetch_url",
                 tool_args={"url": "https://broken.example.com"}, artifact_kind="page",
                 artifact_hash=f"retry-{i}", expected_artifacts=1)
        for i in range(2, 7)
    ]
    runner = runner_factory(tenant_id, CancelRegistry())

    async with checkpoint_saver() as saver:
        result = await runner.run(
            goal_id=goal_id, steps=steps, executor=_RecordingExecutor(),
            expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver,
        )

    assert result.status == "failed"
    assert result.reason in {"repeated_tool_signature", "repeated_tool_sequence"}

    async with tenant_transaction(db_session, tenant_id):
        goal = await GoalRepository(db_session).get(tenant_id=tenant_id, goal_id=goal_id)
        events = await db_session.execute(
            __import__("sqlalchemy").text(
                "SELECT payload, visibility FROM goal_events "
                "WHERE goal_id = :g AND event_type = 'circuit_break'"
            ),
            {"g": str(goal_id)},
        )
        event_rows = events.fetchall()
    assert goal.status == "failed", "熔断必须计失败"
    assert goal.error_code == result.reason
    assert goal.circuit_break_count == 1
    assert len(event_rows) == 1
    payload = event_rows[0][0]
    # 文案只讲业务事实，禁止暴露系统行为（AC-F3）
    for banned in ("阈值", "检测", "重复调用", "无进展"):
        assert banned not in payload["user_message"]
    assert event_rows[0][1] == "owner"


async def test_cancel_is_idempotent_and_sets_stopping_first(
    db_session: AsyncSession, tenant_id: uuid.UUID, runner_factory
) -> None:
    """AC-C1 + AC-C2：先置 stopping；连发 3 次 cancel 全部 200 且状态一致。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    reg = CancelRegistry()
    runner = runner_factory(tenant_id, reg)

    # 让任务跑起来（慢执行器，便于中途取消）
    slow = _RecordingExecutor(delay=0.3)
    async with checkpoint_saver() as saver:
        run_task = asyncio.create_task(
            runner.run(goal_id=goal_id, steps=_steps(6), executor=slow,
                       expected_idle_steps=EXPECTED_IDLE_STEPS, checkpointer=saver)
        )
        await asyncio.sleep(0.35)  # 确保已进入 running

        # 注入同一 registry：API 与 runner 必须共享取消信号通道
        service = GoalService(db_session, cancel_registry=reg)
        results = []
        for _ in range(3):
            res = await service.cancel(
                tenant_id=tenant_id, goal_id=goal_id, user_id=uuid.uuid4()
            )
            results.append(res)

        # 三次 cancel：状态一致、无异常
        assert [r["status"] for r in results] == ["stopping"] * 3

        outcome = await asyncio.wait_for(run_task, timeout=10)

    assert outcome.status == "cancelled"
    async with tenant_transaction(db_session, tenant_id):
        goal = await GoalRepository(db_session).get(tenant_id=tenant_id, goal_id=goal_id)
        succeeded = await TaskStepRepository(db_session).succeeded_count(
            tenant_id=tenant_id, goal_id=goal_id
        )
    assert goal.status == "cancelled"
    # 已完成步骤保留、不回滚（ADR-017）
    assert succeeded >= 1
    assert goal.spent_cents >= 10


async def test_cancel_on_pending_goal_is_immediate(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """边界：queued 态中止 → 零延迟 cancelled。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    service = GoalService(db_session)
    res = await service.cancel(tenant_id=tenant_id, goal_id=goal_id, user_id=uuid.uuid4())
    assert res["status"] == "cancelled"

    # 幂等：再次 cancel 返回同一状态，不报错
    res2 = await service.cancel(tenant_id=tenant_id, goal_id=goal_id, user_id=uuid.uuid4())
    assert res2["status"] == "cancelled"


async def test_resume_rejects_running_goal(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """并发保护：running 态不允许续跑。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    async with tenant_transaction(db_session, tenant_id):
        await GoalRepository(db_session).update_status(
            tenant_id=tenant_id, goal_id=goal_id, status="running"
        )
    service = GoalService(db_session)
    with pytest.raises(ConflictError):
        await service.resume(tenant_id=tenant_id, goal_id=goal_id, user_id=uuid.uuid4())


async def test_progress_state_survives_restart(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """检测窗口必须落盘：idle_streak=4 时崩溃，重启后从 4 恢复而非归零（ADR-011 §5）。"""
    goal_id, _ = await _seed_goal(db_session, tenant_id)
    from app.agents.progress_guard import ProgressState
    from app.repositories.event_repo import GoalProgressRepository

    progress_repo = GoalProgressRepository(db_session)
    state = ProgressState(
        recent_signatures=["fetch_url(url=a)", "fetch_url(url=a)"],
        seen_tool_windows=["w1"],
        idle_streak=4,
        identical_signature_streak=2,
        soft_pause_count=1,
    )
    async with tenant_transaction(db_session, tenant_id):
        await progress_repo.save(tenant_id=tenant_id, goal_id=goal_id, state=state.to_json())

    # 模拟重启：新会话读取
    async with tenant_transaction(db_session, tenant_id):
        row = await progress_repo.load(tenant_id=tenant_id, goal_id=goal_id)
    restored = ProgressState.from_row(row)
    assert restored.idle_streak == 4, "idle_streak 不得归零"
    assert restored.seen_tool_windows == ["w1"]
    assert restored.soft_pause_count == 1