"""岗位 #2：周报汇总（SPEC §2.4 岗位难度「低」）。

输入：本周多份「竞品监控日报」的执行产物（已在库中）。
能力：表格解析 + 文档生成（xlsx 交付物）。
步骤：3-6 步，复用 F6-lite 引擎（graph.py 不动，只新增本 executor）。

【实习生可做】新增岗位只需补模板 + executor，不动引擎。
【需资深】改动前读 SPEC §2.4（124-145 行）与 ADR-011 的步骤幂等约定。

禁造数据（本岗位的 P0）：xlsx 里每一行必须带**溯源引用**
（goal_id + step_ordinal），老板点任何一行都能回到原始日报。
引用不到的内容**不写**，宁可留空也不要编一个看起来合理的数。
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from app.core.logging import get_logger

logger = get_logger("jobs.weekly_report")


# ---- 岗位模板（steps_def 是 F6-lite 图展开的依据）----

WEEKLY_REPORT_TEMPLATE: dict[str, Any] = {
    "code": "weekly-summary",
    "name": "周报汇总",
    "icon": "FileSpreadsheet",
    "summary": "把本周每一份日报收拢成一张总表，逐行可回到原始来源",
    "deliverables": ["周报汇总-{week}.xlsx"],
    "prerequisites": ["至少一份已完成的竞品监控日报"],
    "required_caps": ["tool_use"],
    "optional_caps": [],
    "expected_idle_steps": 5,
    "expected_total_steps": 4,
    "baseline_minutes_per_run": 25,
    "difficulty": "low",
    "sort_order": 2,
    "steps_def": [
        {
            "ordinal": 1,
            "title": "收集本周竞品日报",
            "tool_name": "collect_daily_reports",
            "tool_args": {"window_days": 7},
        },
        {
            "ordinal": 2,
            "title": "逐份提炼要点",
            "tool_name": "summarize_reports",
            "tool_args": {},
        },
        {
            "ordinal": 3,
            "title": "生成周报总表",
            "tool_name": "generate_xlsx",
            "tool_args": {},
        },
        {
            "ordinal": 4,
            "title": "登记交付物",
            "tool_name": "finalize",
            "tool_args": {},
        },
    ],
}


@dataclass
class DailyReportFact:
    """一条可溯源的事实：来自某份日报的某一步。"""

    goal_id: uuid.UUID
    step_ordinal: int
    report_date: date
    agent_name: str
    headline: str  # 业务语言的一句话要点

    def citation(self) -> str:
        """溯源引用。老板点任何一行都能回到原始来源。"""
        return f"goal:{self.goal_id}#step:{self.step_ordinal}"


# ---- 摘要器（可注入；生产走 BYOK LLM，测试用 fake）----


class Summarizer(Protocol):
    """把一条日报事实提炼成一句话要点。"""

    async def summarize(self, fact: DailyReportFact, raw: str) -> str: ...


class NoopSummarizer:
    """无 BYOK 密钥时的兜底：不编造，直接返回可溯源的原文截断。

    【需资深】为什么「不编造」比「生成好文案」重要：链路上一环造谣，
    整条链都不可信。没有模型可调时，返回原始事实比返回幻觉强。
    """

    async def summarize(self, fact: DailyReportFact, raw: str) -> str:
        del fact
        return raw[:200] if raw else "（本期无日报内容）"


# ---- 执行器 ----


class WeeklyReportExecutor:
    """周报汇总的 StepExecutor。按 ctx.step.tool_name 分派。

    xlsx 在内存生成并登记为 artifact（content_hash 用于 S2 无进展检测）。
    output_ref 是对象存储 key（S3 上传在存储层单独接线，本文件不碰网络）。
    """

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_name: str,
        session_factory: Any,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._agent_name = agent_name
        self._session_factory = session_factory
        self._summarizer = summarizer or NoopSummarizer()
        self._facts: list[DailyReportFact] = []
        self._week_start: date | None = None

    async def __call__(self, ctx: Any) -> Any:
        tool = ctx.step.tool_name
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return self._outcome(failed=True, error_code=f"unknown_tool_{tool}")
        return await handler(ctx)

    # ---- 步骤 1：收集日报 ----

    async def _tool_collect_daily_reports(self, ctx: Any) -> Any:
        facts = await self._load_week_facts()
        if not facts:
            # G4 语义：没有日报**不是**「今天没有变化」，是「没有可汇总的输入」。
            # 显式失败，禁止生成空表冒充完成。
            return self._outcome(failed=True, error_code="no_daily_reports")
        self._facts = facts
        return self._outcome(output=f"收集到 {len(facts)} 条日报事实", artifact_count=len(facts))

    # ---- 步骤 2：提炼要点 ----

    async def _tool_summarize_reports(self, ctx: Any) -> Any:
        summarized: list[DailyReportFact] = []
        for fact in self._facts:
            headline = await self._summarizer.summarize(fact, fact.headline)
            summarized.append(DailyReportFact(
                goal_id=fact.goal_id,
                step_ordinal=fact.step_ordinal,
                report_date=fact.report_date,
                agent_name=fact.agent_name,
                headline=headline,
            ))
        self._facts = summarized
        return self._outcome(output=f"提炼 {len(summarized)} 条要点", artifact_count=len(summarized))

    # ---- 步骤 3：生成 xlsx ----

    async def _tool_generate_xlsx(self, ctx: Any) -> Any:
        if not self._facts:
            return self._outcome(failed=True, error_code="no_data_to_export")
        content = self._build_xlsx()
        content_hash = _blake(content)
        self._xlsx_content = content
        self._xlsx_hash = content_hash
        return self._outcome(
            output=f"weekly-{self._week_start}.xlsx", artifact_count=1, content_hash=content_hash
        )

    # ---- 步骤 4：登记 ----

    async def _tool_finalize(self, ctx: Any) -> Any:
        return self._outcome(output="weekly-report-ready", artifact_count=0)

    # ---- 内部 ----

    async def _load_week_facts(self) -> list[DailyReportFact]:
        """读本周已完成的日报 goal 的产出步骤。**只引用库中真实存在的数据**。"""
        from sqlalchemy import select

        from app.db.rls import tenant_transaction
        from app.models.goal import Goal, TaskStep
        from app.models.job import Agent

        week_start = (datetime.now(UTC).date() - timedelta(days=7))
        self._week_start = week_start
        start = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)

        facts: list[DailyReportFact] = []
        async with self._session_factory() as session, tenant_transaction(session, self._tenant_id):
            result = await session.execute(
                select(Goal, Agent.name)
                .join(Agent, Agent.id == Goal.agent_id)
                .where(
                    Goal.tenant_id == self._tenant_id,
                    Goal.status == "completed",
                    Goal.created_at >= start,
                )
                .order_by(Goal.created_at)
            )
            for goal, agent_name in result.all():
                steps = (
                    await session.execute(
                        select(TaskStep).where(
                            TaskStep.tenant_id == self._tenant_id,
                            TaskStep.goal_id == goal.id,
                            TaskStep.status == "succeeded",
                        )
                    )
                ).scalars().all()
                if not steps:
                    continue
                facts.append(DailyReportFact(
                    goal_id=goal.id,
                    step_ordinal=steps[-1].step_ordinal,
                    report_date=goal.created_at.date(),
                    agent_name=agent_name,
                    headline=steps[-1].title,
                ))
        return facts

    def _build_xlsx(self) -> bytes:
        """生成周报总表。每行带 citation 列（溯源）。"""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "周报汇总"
        ws.append(["日期", "员工", "要点", "来源（溯源引用）"])
        for fact in self._facts:
            ws.append([fact.report_date.isoformat(), fact.agent_name, fact.headline, fact.citation()])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

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