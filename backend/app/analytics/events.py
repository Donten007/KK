"""埋点事件白名单（TRACKING-GUARD 防线 1 / openapi `/analytics/events` enum）。

**单一数据源**：本 frozenset 是事件名的唯一权威，`verify-tracking.sh` 与
TRACKING-WHITELIST.md 做双向差集校验，任一方向有差异即阻断发布。
禁止在 schema 与 service 各写一份。

已剔除 `credit_purchased`：纯 BYOK 后无充值，该事件无业务含义
（DECISION-CHANGES 变更二 + openapi enum 已同步删除）。
"""

from __future__ import annotations

from typing import Final, Literal, get_args

# 31 个事件（openapi enum 与此一致）
ALLOWED_EVENTS: Final = frozenset(
    {
        # 获客
        "signup_complete",
        "company_size_selected",
        "job_template_viewed",
        "job_template_selected",
        # 激活
        "agent_created",
        "first_run_submitted",
        "first_run_completed",
        "first_report_viewed",
        # 留存
        "session_start",
        "owner_report_viewed",
        "admin_usage_viewed",
        "daily_report_clicked",
        "agent_switched",
        # 核心假设验证
        "task_completed",
        "task_escalated_to_human",
        "escalation_resolved",
        "task_failed",
        "task_resumed_from_checkpoint",
        "task_circuit_broken",
        "budget_warning_triggered",
        "budget_exhausted",
        "cost_viewed",
        "owner_report_cost_expanded",
        "trust_metric_expanded",
        # 转化
        "pricing_page_viewed",
        "upgrade_click",
        "subscription_started",
        "agent_second_created",
        # 异常
        "error_occurred",
        "model_fallback_triggered",
        "key_invalid_detected",
    }
)

# Pydantic Literal 联合类型：不在枚举内 → 422 整条拒绝（防线 1 在契约层生效）
EventName = Literal[
    "signup_complete",
    "company_size_selected",
    "job_template_viewed",
    "job_template_selected",
    "agent_created",
    "first_run_submitted",
    "first_run_completed",
    "first_report_viewed",
    "session_start",
    "owner_report_viewed",
    "admin_usage_viewed",
    "daily_report_clicked",
    "agent_switched",
    "task_completed",
    "task_escalated_to_human",
    "escalation_resolved",
    "task_failed",
    "task_resumed_from_checkpoint",
    "task_circuit_broken",
    "budget_warning_triggered",
    "budget_exhausted",
    "cost_viewed",
    "owner_report_cost_expanded",
    "trust_metric_expanded",
    "pricing_page_viewed",
    "upgrade_click",
    "subscription_started",
    "agent_second_created",
    "error_occurred",
    "model_fallback_triggered",
    "key_invalid_detected",
]

# Literal 与 frozenset 必须一致（测试断言，防止两处漂移）
LITERAL_EVENTS: Final = frozenset(get_args(EventName))


def is_allowed_event(name: str) -> bool:
    return name in ALLOWED_EVENTS