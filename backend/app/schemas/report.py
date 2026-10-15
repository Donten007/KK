"""汇报 schema（openapi DailyReport / WeeklyReport / CostBreakdown 对齐）。

四板块固定顺序不可调：做完了 → 要你管 → 我停下来过 → 花的钱。
顺序本身承载信息（SPEC §7.4）：先看成绩，再看要处理的，再看协作，最后才看钱。

四块空状态**刻意各不相同**（省略比报错更伤信任）：
| 板块 | 为 0 时 |
|------|---------|
| ① 做完了 | 不隐藏，写「今天没有需要产出的活，员工在待命」 |
| ② 要你管 | 返回 null，前端**整个板块不渲染**（不是写「一切正常」） |
| ③ 我停下来过 | 必渲染，写「今天没有员工打断你。」 |
| ④ 花的钱 | 必渲染，写「今天没有产生模型调用费用。」 |
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportOutput(BaseModel):
    name: str
    kind: str = Field(pattern="^(file|row|record|report)$")
    size_bytes: int = 0
    asset_id: str | None = None


class Block1Completed(BaseModel):
    """① 今天做完了什么。has_content=false 时前端渲染空状态文案而非隐藏板块。"""

    has_content: bool
    items: list[dict[str, Any]] = Field(default_factory=list)


class Block2NeedsAction(BaseModel):
    """② 要你管。为 0 时整个对象为 null（前端不画这一块）。"""

    pending_count: int
    agents_stopped: bool


class Block3Stopped(BaseModel):
    """③ 我停下来过。必渲染。total_this_month 必须来自真实事件流统计，禁止编造。"""

    resolved_count: int
    awaiting_count: int
    total_this_month: int
    message: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class Block4Cost(BaseModel):
    """④ 花的钱。必渲染。为 0 时写「今天没有产生模型调用费用。」而不是 ¥0.00。"""

    today_cost_cents: int
    monthly_forecast_cents: int
    saved_minutes_today: int
    saved_hours: float | None = None
    baseline_configured: bool = False
    baseline_minutes_per_run: float | None = None
    hourly_rate_cny: float | None = None
    message: str


class AgentReport(BaseModel):
    """某员工当日明细。**当日未执行也必须出现在列表中**（不得静默跳过，AC-10）。"""

    agent_id: str
    agent_name: str
    status: str = Field(pattern="^(completed|partial|stuck|not_run)$")
    done_section: dict[str, Any] = Field(default_factory=dict)
    needs_you_section: dict[str, Any] = Field(default_factory=dict)
    stopped_section: dict[str, Any] = Field(default_factory=dict)
    cost_section: dict[str, Any] = Field(default_factory=dict)
    roi_section: dict[str, Any] = Field(default_factory=dict)


class DailyReport(BaseModel):
    report_date: date
    on_duty_count: int
    standby_count: int
    block1_completed: Block1Completed
    block2_needs_action: Block2NeedsAction | None = None
    block3_stopped: Block3Stopped
    block4_cost: Block4Cost
    agents: list[AgentReport] = Field(default_factory=list)
    generated_at: datetime


class BacklogItem(BaseModel):
    """积压项。**禁止折叠**——waiting_days 是升级信号（openapi 明确要求）。"""

    pending_id: str
    agent_id: str
    agent_name: str
    reason: str
    waiting_days: int
    created_at: datetime


class TrustSummary(BaseModel):
    """信任指标。**禁止硬编码、禁止凑数、无数据时不编造**。

    数据来源：task_escalated_to_human × escalation_resolved 配对计数。
    """

    escalated_count: int
    resolved_count: int
    unresolved_count: int
    main_sentence: str
    all_resolved: bool


class WeeklyReport(BaseModel):
    week_start: date
    week_end: date
    agents: list[AgentReport] = Field(default_factory=list)
    backlog_count: int
    backlog_items: list[BacklogItem] = Field(default_factory=list)
    trust_summary: TrustSummary
    roi: dict[str, Any] = Field(default_factory=dict)


class CostBreakdownItem(BaseModel):
    agent_id: str
    agent_name: str
    task_count: int
    cost_cents: int


class CostBreakdown(BaseModel):
    """员工维度成本构成（业务口径，**无 token**）。"""

    items: list[CostBreakdownItem] = Field(default_factory=list)
    total_cost_cents: int