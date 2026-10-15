"""岗位 #4：客户跟进催办（SPEC §2.4，难度「中」）。

输入：客户跟进表格（CSV/xlsx 上传，走资产中心已有的上传能力；
解析后的结构化记录随 goal.input_payload 的 followup_records 进入执行器）。
能力：表格解析 + 超期识别（N 天可配，默认 7）+ 话术生成（BYOK）。
步骤：6 步，复用 F6-lite 引擎（graph.py 不动，只新增本 executor）。

「主动升级给人」机制（本岗位验证的差异化卖点）：
跟进日期缺失/无法识别的记录 = 拿不准 = 升级 waiting_approval，
走已实现的 SoftPauseSignal + pending_items 机制（/pending 页已就绪）。
老板在 /pending 批准后 resume，本步骤检测到该 goal 已有已处理的
待确认项，即按「跳过拿不准、只催可确认的」继续——批准有明确语义，
不是原样重跑再暂停一次的死循环。

禁造数据（P0）：话术只允许引用库/输入中真实存在的记录
（客户名 + 最后跟进日期 + 来源行号），引用不到就不生成。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.jobs.followup_script import (
    DEFAULT_THRESHOLD_DAYS,
    NoopScriptWriter,
    ScriptWriter,
    build_chase_workbook,
    days_since,
    is_overdue,
    is_valid_threshold,
    parse_followup_records,
)

logger = get_logger("jobs.followup_chase")


# ---- 岗位模板（steps_def 是 F6-lite 图展开的依据）----

FOLLOWUP_CHASE_TEMPLATE: dict[str, Any] = {
    "code": "followup-chase",
    "name": "客户跟进催办",
    "icon": "PhoneCall",
    "summary": "读客户跟进表格，找出超期未跟进的客户，写好催办话术；拿不准的停下来问你",
    "deliverables": ["催办清单-{date}.xlsx"],
    "prerequisites": ["客户跟进表格（CSV/xlsx）已上传到资产中心"],
    "required_caps": ["tool_use"],
    "optional_caps": [],
    "expected_idle_steps": 5,
    "expected_total_steps": 6,
    "baseline_minutes_per_run": 30,
    "difficulty": "medium",
    "sort_order": 4,
    "steps_def": [
        {
            "ordinal": 1,
            "title": "读取跟进表格",
            "tool_name": "load_followup_table",
            "tool_args": {},
        },
        {
            "ordinal": 2,
            "title": "找出超期未跟进的客户",
            "tool_name": "identify_overdue",
            "tool_args": {},
        },
        {
            "ordinal": 3,
            "title": "拿不准的升级确认",
            "tool_name": "escalate_uncertain",
            "tool_args": {},
        },
        {
            "ordinal": 4,
            "title": "起草催办话术",
            "tool_name": "draft_scripts",
            "tool_args": {},
        },
        {
            "ordinal": 5,
            "title": "生成催办清单",
            "tool_name": "build_deliverable",
            "tool_args": {},
        },
        {
            "ordinal": 6,
            "title": "登记交付物",
            "tool_name": "finalize",
            "tool_args": {},
        },
    ],
}


class FollowupChaseExecutor:
    """客户跟进催办的 StepExecutor。按 ctx.step.tool_name 分派。

    话术生成走注入的 ScriptWriter（生产接 BYOK 模型网关，测试用 fake/Noop）。
    """

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_name: str,
        session_factory: Any,
        script_writer: ScriptWriter | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._agent_name = agent_name
        self._session_factory = session_factory
        self._writer = script_writer or NoopScriptWriter()
        self._goal_id: uuid.UUID | None = None
        self._step_title = ""
        self._step_ordinal = 0
        self._input_asset_id: str | None = None
        self._threshold_days = DEFAULT_THRESHOLD_DAYS
        self._valid: list[Any] = []
        self._overdue: list[tuple[Any, int, str]] = []
        self._uncertain: list[Any] = []
        self._unusable: list[Any] = []
        self._xlsx_content = b""

    async def __call__(self, ctx: Any) -> Any:
        tool = ctx.step.tool_name
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return self._outcome(failed=True, error_code=f"unknown_tool_{tool}")
        self._goal_id = ctx.goal_id
        self._step_title = ctx.step.title
        self._step_ordinal = ctx.step.ordinal
        return await handler(ctx)

    # ---- 步骤 1：读表 ----

    async def _tool_load_followup_table(self, ctx: Any) -> Any:
        payload = await self._load_input_payload()
        if payload is None:
            return self._outcome(failed=True, error_code="goal_not_found")
        raw_rows = payload.get("followup_records")
        if not isinstance(raw_rows, list) or not raw_rows:
            # G4 语义：没有可解析的输入不是「没有超期客户」，是「没有输入」。
            return self._outcome(failed=True, error_code="no_followup_records")
        asset_id = payload.get("input_asset_id")
        self._input_asset_id = str(asset_id) if asset_id else None
        threshold = payload.get("threshold_days", DEFAULT_THRESHOLD_DAYS)
        if not is_valid_threshold(threshold):
            return self._outcome(failed=True, error_code="invalid_threshold")
        self._threshold_days = threshold
        parsed = parse_followup_records(raw_rows)
        self._uncertain, self._unusable = parsed.uncertain, parsed.unusable
        self._valid = parsed.valid
        return self._outcome(output=f"读取 {len(raw_rows)} 条跟进记录", artifact_count=0)

    # ---- 步骤 2：超期识别 ----

    async def _tool_identify_overdue(self, ctx: Any) -> Any:
        today = datetime.now(UTC).date()
        overdue: list[tuple[Any, int, str]] = []
        for record in self._valid:
            if is_overdue(record, today, self._threshold_days):
                overdue.append((record, days_since(record, today), ""))
        self._overdue = overdue
        return self._outcome(
            output=f"识别出 {len(overdue)} 个超期客户", artifact_count=0
        )

    # ---- 步骤 3：升级确认（软暂停的入口）----

    async def _tool_escalate_uncertain(self, ctx: Any) -> Any:
        if not self._uncertain:
            return self._outcome(output="没有拿不准的记录", artifact_count=0)
        if await self._has_resolved_escalation(ctx.goal_id):
            # 老板已在 /pending 处理过：按「跳过拿不准、只催可确认的」继续。
            # 未确认记录仍进「待人工确认」页（带来源行号），不悄悄吞掉。
            return self._outcome(output=f"跳过 {len(self._uncertain)} 条待确认记录", artifact_count=0)
        listing = "、".join(
            f"{r.customer}（来源行 {r.row_no}）" for r in self._uncertain
        )
        from app.agents.graph import SoftPauseSignal

        raise SoftPauseSignal(
            f"有 {len(self._uncertain)} 条跟进记录拿不准：{listing}。"
            "它们的跟进日期缺失或无法识别，我不能猜。确认后我再继续催可确认的。",
            step_title=self._step_title,
            step_ordinal=self._step_ordinal,
        )

    # ---- 步骤 4：话术草拟 ----

    async def _tool_draft_scripts(self, ctx: Any) -> Any:
        drafted: list[tuple[Any, int, str]] = []
        for record, overdue_days, _ in self._overdue:
            script = await self._writer.draft(record, overdue_days)
            drafted.append((record, overdue_days, script))
        self._overdue = drafted
        return self._outcome(output=f"起草 {len(drafted)} 条话术", artifact_count=0)

    # ---- 步骤 5：交付物 ----

    async def _tool_build_deliverable(self, ctx: Any) -> Any:
        content = build_chase_workbook(
            overdue=self._overdue,
            uncertain=self._uncertain,
            unusable=self._unusable,
            today=datetime.now(UTC).date(),
            input_asset_id=self._input_asset_id,
        )
        self._xlsx_content = content
        return self._outcome(
            output=f"chase-{datetime.now(UTC).date()}.xlsx",
            artifact_count=1,
            content_hash=_blake(content),
        )

    # ---- 步骤 6：登记 ----

    async def _tool_finalize(self, ctx: Any) -> Any:
        return self._outcome(output="followup-chase-ready", artifact_count=0)

    # ---- 内部 ----

    async def _load_input_payload(self) -> dict[str, Any] | None:
        """读本 goal 的 input_payload。只读真实存在的行，不猜。"""
        from sqlalchemy import select

        from app.db.rls import tenant_transaction
        from app.models.goal import Goal

        async with self._session_factory() as session, tenant_transaction(session, self._tenant_id):
            row = (
                await session.execute(
                    select(Goal.input_payload).where(
                        Goal.tenant_id == self._tenant_id, Goal.id == self._goal_id
                    )
                )
            ).first()
        return dict(row[0]) if row and row[0] else None

    async def _has_resolved_escalation(self, goal_id: uuid.UUID) -> bool:
        """该 goal 是否已有老板处理过的待确认项（approve/amend 都算）。"""
        from sqlalchemy import select

        from app.db.rls import tenant_transaction
        from app.models.report_support import PendingItem

        async with self._session_factory() as session, tenant_transaction(session, self._tenant_id):
            row = (
                await session.execute(
                    select(PendingItem.id)
                    .where(
                        PendingItem.tenant_id == self._tenant_id,
                        PendingItem.goal_id == goal_id,
                        PendingItem.status == "resolved",
                    )
                    .limit(1)
                )
            ).first()
        return row is not None

    def _outcome(
        self,
        *,
        output: str | None = None,
        failed: bool = False,
        error_code: str | None = None,
        artifact_count: int = 0,
        content_hash: str = "",
    ) -> Any:
        from app.agents.graph import StepOutcome

        return StepOutcome(
            output_ref=output,
            status="failed" if failed else "succeeded",
            error_code=error_code,
            artifact_ids=[uuid.uuid4() for _ in range(artifact_count)],
            cost_cents=0,
            model_id=None,
        )


def _blake(content: bytes) -> str:
    from hashlib import blake2b

    return blake2b(content, digest_size=32).hexdigest()
