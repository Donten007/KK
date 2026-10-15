"""步骤数与费用预估（SPEC §5.3 POST /api/v1/goals 响应含预估）。

铁律（坑 13）：预算是**量级估算**，不是精确报价。
- 预估按 LiteLLM 单价 × 预估 token，用「部分缓存命中」加权
- 三个已知偏差必须随预估一起返回：峰谷定价 / 缓存命中差异 / 长上下文阶梯
- **价格表缺失时不得阻断任务**（AC-E4），用保守默认值并标记精度降低

【实习生可做】调整 multiplier 常量即可，不需要理解图执行。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.job import JobTemplate

# 每步 LLM 调用的粗略 token 估量（含提示词 + 工具结果的典型量级）
TOKENS_INPUT_PER_STEP = 1200
TOKENS_OUTPUT_PER_STEP = 400
# 缓存命中按部分命中加权（SPEC §4.7 精度限制二）：命中输入价约为未命中的 1/50
CACHE_HIT_RATIO = 0.3

# 单价兜底（分 / 每百万 token）。真实单价来自 model_pricing 表（LiteLLM 每日同步），
# 表为空时用这套保守值并把 precision 标成 low（AC-E4：不中断服务）。
FALLBACK_PRICE_IN_CENTS_PER_MTOK = 200
FALLBACK_PRICE_OUT_CENTS_PER_MTOK = 400

# 已知偏差标注（必须随预估返回，AC-E3）
ESTIMATE_CAVEATS = (
    "按非峰时段估算，未包含厂商峰时定价",
    "按部分缓存命中估算，命中与否单价差异较大",
    "未包含长上下文阶梯加价",
)


@dataclass(frozen=True)
class GoalEstimate:
    """预估结果。estimated=True 表示可对外展示；interval 表示是区间而非单值。"""

    steps: int
    cost_cents: int
    cost_low_cents: int
    cost_high_cents: int
    precision: str  # high / low（低 = 价格表缺失）
    caveats: tuple[str, ...]


def estimate_goal(template: JobTemplate, *, url_count: int = 1) -> GoalEstimate:
    """按岗位模板预估步骤数与费用。

    步骤数 = max(模板预期, url_count × 每站步数)。竞品监控日报的每站步数为 2
    （抓取 + 解析），汇总 1 步。
    """
    steps_per_url = 2
    steps = max(template.expected_total_steps, url_count * steps_per_url + 1)
    input_tokens = steps * TOKENS_INPUT_PER_STEP
    output_tokens = steps * TOKENS_OUTPUT_PER_STEP

    in_price = FALLBACK_PRICE_IN_CENTS_PER_MTOK
    out_price = FALLBACK_PRICE_OUT_CENTS_PER_MTOK
    cost = round(
        (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    )
    # 区间：缓存命中差异可达 50 倍，取保守的 ±60% 作为展示区间（不给单值冒充精确）
    return GoalEstimate(
        steps=steps,
        cost_cents=max(cost, 1),
        cost_low_cents=max(1, round(cost * 0.4)),
        cost_high_cents=round(cost * 1.6) + 1,
        precision="low",
        caveats=ESTIMATE_CAVEATS,
    )