"""用量 schema：**两个完全独立的 schema**（AC-14b / ADR-017 / SPEC C5 裁决）。

铁律：`OwnerUsageSchema` 里**不存在** token / model / duration 字段——
连 nullable 都不行。原因不是「我们记得剔除」，而是**契约层就让泄漏不可能发生**：
前端用 openapi-typescript 生成的类型里没有这些字段，owner 组件访问即编译报错。

数据源同样从路径上断开：owner 口径读 `usage_daily`（成本聚合），
**不读** `usage_records` 的 token 字段（AC-C6）。
"""

from __future__ import annotations

from pydantic import BaseModel


class OwnerUsageItem(BaseModel):
    agent_id: str
    agent_name: str
    task_count: int
    cost_cents: int


class OwnerUsageDay(BaseModel):
    date: str
    cost_cents: int


class OwnerRoi(BaseModel):
    """人力折算。**折算必须从真实执行记录聚合**，禁止用典型值估算。

    baseline_configured=false 时前端**必须显示配置引导**，不得显示 0
    （0 会被读成「没省时间」）。
    """

    saved_hours: float | None
    baseline_configured: bool
    baseline_minutes_per_run: float | None
    hourly_rate_cny: float | None
    roi_ratio: float | None


class OwnerUsageSummary(BaseModel):
    """owner 口径业务视图。

    [P0] 本 schema **刻意不含** input_tokens / output_tokens / model /
    cache_hit_tokens / latency_ms / duration_ms —— 任何字段都不加。
    加字段前请先读 AC-14b 与 SPEC C5 裁决。
    """

    period: str
    total_cost_cents: int
    total_task_count: int
    cost_by_agent: list[OwnerUsageItem] = []
    cost_by_day: list[OwnerUsageDay] = []
    roi: OwnerRoi


class AdminUsageByModel(BaseModel):
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    task_count: int
    cost_cents: int


class AdminUsageByAgent(BaseModel):
    agent_id: str
    input_tokens: int
    output_tokens: int
    cost_cents: int


class AdminUsageSummary(BaseModel):
    """admin 口径技术视图（完整 token 明细与模型构成）。仅 admin 角色可见。"""

    period: str
    total_cost_cents: int
    usage_by_model: list[AdminUsageByModel] = []
    usage_by_agent: list[AdminUsageByAgent] = []
    budget_trigger_rate: float