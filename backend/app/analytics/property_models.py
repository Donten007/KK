"""每事件独立属性模型（TRACKING-GUARD 防线 2）。

**为什么不用统一 dict[str, Any]**：统一 dict 等于没有防线 2。
独立模型让「这个事件能记什么」成为**类型定义**而不是运行时约定——
新增属性必须先改类型定义，类型定义与白名单文档一起 review。

每事件属性集与 TRACKING-WHITELIST.md 第二节一一对应。
"""

from __future__ import annotations

from typing import Final

# 每个事件的合法属性名（值类型统一为 str/int/float/bool/None，入库前过滤）
EVENT_PROPERTIES: Final[dict[str, frozenset[str]]] = {
    # 获客
    "signup_complete": frozenset({"source"}),
    "company_size_selected": frozenset({"size_bucket"}),
    "job_template_viewed": frozenset({"template_count"}),
    "job_template_selected": frozenset(
        {"job_template_id", "position", "expanded_deliverable"}
    ),
    # 激活
    "agent_created": frozenset({"job_template_id", "is_first_agent"}),
    "first_run_submitted": frozenset({"job_template_id"}),
    "first_run_completed": frozenset({"job_template_id", "duration_sec", "cost_cny"}),
    "first_report_viewed": frozenset(),
    # 留存
    "session_start": frozenset(),
    "owner_report_viewed": frozenset({"is_same_day_as_run"}),
    "admin_usage_viewed": frozenset(),
    "daily_report_clicked": frozenset({"channel"}),
    "agent_switched": frozenset({"from_agent", "to_agent"}),
    # 核心假设验证
    "task_completed": frozenset({"job_template_id", "step_count", "cost_cny", "duration_sec"}),
    "task_escalated_to_human": frozenset({"job_template_id", "reason_code"}),
    "escalation_resolved": frozenset({"job_template_id", "resolution", "resolve_sec"}),
    "task_failed": frozenset({"job_template_id", "failure_type"}),
    "task_resumed_from_checkpoint": frozenset({"job_template_id", "resumed_at_step"}),
    "task_circuit_broken": frozenset({"job_template_id", "broken_at_step", "signal"}),
    "budget_warning_triggered": frozenset({"agent_id", "pct"}),
    "budget_exhausted": frozenset({"agent_id"}),
    "cost_viewed": frozenset({"surface"}),
    "owner_report_cost_expanded": frozenset(),
    "trust_metric_expanded": frozenset(),
    # 转化
    "pricing_page_viewed": frozenset({"plan_interest"}),
    "upgrade_click": frozenset({"from_plan", "to_plan"}),
    "subscription_started": frozenset({"plan", "billing_cycle"}),
    "agent_second_created": frozenset(),
    # 异常
    "error_occurred": frozenset({"surface", "error_type"}),
    "model_fallback_triggered": frozenset({"from_model", "to_model"}),
    "key_invalid_detected": frozenset({"provider"}),
}

# 属性值类型白名单：只允许标量。嵌套对象/数组一律丢弃（防内容夹带）
ALLOWED_VALUE_TYPES: Final = (str, int, float, bool)

# 禁记属性名（属性名黑名单，防线 3 的一部分）。
# 内容类字段的**名字会变**（content/text/payload/body），所以真正起作用的是
# 下面的长度阈值；这份名单只挡住最明显的几种（TRACKING-GUARD 防线 3）。
BANNED_PROPERTY_KEYS: Final = frozenset(
    {
        # 文件名（客户业务信息）
        "file_name",
        "filename",
        "document_name",
        "doc_name",
        "attachment_name",
        # 内容类
        "content",
        "text",
        "body",
        "payload",
        "prompt",
        "completion",
        "message_body",
        "html",
        "chunk",
        "snippet",
        # 网络标识（无例外承诺：不采集 IP / UA）
        "ip",
        "ip_address",
        "user_agent",
        "useragent",
        "ua",
        "device_id",
        "device_fingerprint",
        # 凭据
        "api_key",
        "token",
        "password",
        "secret",
        "email",
    }
)

# 防线 3 的核心阈值：单个字符串属性 > 500 字符 → **整条丢弃**。
# 本产品合法属性（ID、状态码、时长、金额、模板 ID）均不超过 50 字符。
MAX_VALUE_LENGTH = 500

# 逐事件调高阈值必须显式声明，禁止全局放宽（TRACKING-GUARD §七 第 2 点）。
# 本产品当前**没有任何事件**需要调高——保持空表即证明「阈值未被全局放宽」。
PER_EVENT_VALUE_LIMITS: Final[dict[str, int]] = {}


def allowed_properties(event: str) -> frozenset[str]:
    return EVENT_PROPERTIES.get(event, frozenset())


def value_limit_for(event: str) -> int:
    """该事件的字符串长度上限。缺省 500，逐事件显式覆盖。"""
    return PER_EVENT_VALUE_LIMITS.get(event, MAX_VALUE_LENGTH)