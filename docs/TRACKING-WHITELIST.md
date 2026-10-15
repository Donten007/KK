# 埋点事件白名单（Phase 2 实施依据）

> **状态**：PM 定稿，可直接并入 SPEC.md
> **版本**：2026-10-15
> **依据**：PRD §11.3 + §12 验收标准 + §8.4 Go/No-Go 判据

---

## 一、实现约束（架构侧已确认可行）

| 约束 | 内容 | 来源 |
|---|---|---|
| **前端不采集** | `trackEvent()` 埋点，**禁止引入第三方 SDK**。理由：第三方 SDK 自动采集 UA/IP 上报外部端点，技术上无法证伪我们的数据主权承诺 | 架构确认 |
| **后端必须过滤后入库** | 后端只接受「事件名 + 属性白名单」，**未知属性一律丢弃**。前端不采集不够，后端也要守| 架构 ADR-012 |
| **事件表走 RLS** | 保留 180 天 | 架构确认 |
| **禁记字段** | IP / UA / 原始输入内容 / 文件名 | PRD §11.3 |

---

## 二、事件白名单（完整清单）

> **白名单原则**：不在此表内的事件名一律丢弃。每条事件必须能回答一个明确的业务问题，否则不埋。

### 2.1 获客（4 个）

| 事件名 | 触发时机 | 关键属性 | 回答什么问题 |
|---|---|---|---|
| `signup_complete` | 注册完成 | `source`（渠道） | 新用户从哪来 |
| `company_size_selected` | 员工规模页点击选项 | `size_bucket` | 是否回答了第一个问题 |
| `job_template_viewed` | 进入岗位库 | `template_count` | 岗位库是否被看到 |
| `job_template_selected` | 点击某岗位卡片 | `job_template_id`, `position`, `expanded_deliverable`（**是否展开了交付物区**） | 哪张卡片被选、**五要素顺序调整对转化的影响** |

> `expanded_deliverable` 是专门为「交付物前置」这个改动加的——总监提示过埋点污染问题，这个字段让我们能验证新顺序是否真的提升了选中率。

### 2.2 激活（4 个）

| 事件名 | 触发时机 | 关键属性 | 回答什么问题 |
|---|---|---|---|
| `agent_created` | AI 员工创建成功 | `job_template_id`, `is_first_agent` | 首个员工创建率 |
| `first_run_submitted` | 首次试跑提交 | `job_template_id` | 有多少走到试跑 |
| `first_run_completed` | 首次试跑完成 | `job_template_id`, `duration_sec`, `cost_cny` | **激活定义的核心事件** |
| `first_report_viewed` | 首次查看汇报 | — | 老板是否看到了交付物 |

> **激活定义**：首个 AI 员工首次成功跑完 **且** 老板查看了汇报。三个事件缺一不算激活。

### 2.3 留存（5 个）

| 事件名 | 触发时机 | 关键属性 | 回答什么问题 |
|---|---|---|---|
| `session_start` | 会话开始 | — | DAU/MAU |
| `owner_report_viewed` | 老板查看汇报页 | `is_same_day_as_run` | **最重要的留存指标** |
| `admin_usage_viewed` | 管理员查看用量页 | — | 管理员是否用得上（**与上一条分开埋点，否则无法衡量老板是否真在用汇报页**） |
| `daily_report_clicked` | 点击企微推送 | `channel` | 推送是否有效 |
| `agent_switched` | 在多个 AI 员工间切换 | `from_agent`, `to_agent` | 多员工是否真在用 |

### 2.4 核心假设验证（11 个 — 产出 Go/No-Go 判据）

| 事件名 | 触发时机 | 关键属性 | 支撑判据 |
|---|---|---|---|
| `task_completed` | 任务完成 | `job_template_id`, `step_count`, `cost_cny`, `duration_sec` | **TCR 分子** |
| `task_escalated_to_human` | AI 主动升级给人 | `job_template_id`, `reason_code` | **HITL 分子 + 信任闭环指标** |
| `escalation_resolved` | 人工确认完成 | `job_template_id`, `resolution`（accept/edit/skip）, `resolve_sec` | **信任闭环指标配对**（与上一条必须配对） |
| `task_failed` | 任务失败 | `job_template_id`, `failure_type` | **失败率** |
| `task_resumed_from_checkpoint` | 从断点续跑 | `job_template_id`, `resumed_at_step` | 断点续跑生效（对撞 Manus 差评） |
| `task_circuit_broken` | 熔断触发 | `job_template_id`, `broken_at_step`, `signal`（S1a/S2） | **熔断率（计失败）** |
| `budget_warning_triggered` | 达80% 预警 | `agent_id`, `pct` | 预算闸门生效 |
| `budget_exhausted` | 达 100% 停止 | `agent_id` | 预算硬上限生效 |
| `cost_viewed` | 老板查看成本 | `surface`（trial/report/inline） | 成本透明是否被使用 |
| `owner_report_cost_expanded` | 同页展开成本构成 | — | 下钻路径是否被使用 |
| `trust_metric_expanded` | 展开「怎么算出来的」 | — | 有多少老板真的追问技术口径 |

> **恒等式校验（架构 ADR-015）**：`TCR + HITL + 失败率 = 100%`。**熔断必须计入失败**，否则熔断率会伪装成成功率。

### 2.5 转化（4 个）

| 事件名 | 触发时机 | 关键属性 |
|---|---|---|
| `pricing_page_viewed` | 查看定价页 | `plan_interest` |
| `upgrade_click` | 点击升级 | `from_plan`, `to_plan` |
| `subscription_started` | 订阅成功 | `plan`, `billing_cycle` |
| `agent_second_created` | 雇第二个员工 | — |

> **`credit_purchased`（充值）已删除** —— 纯 BYOK 后无充值行为，该事件不可能触发（2026-10-15 决策变更二）。代码 `ALLOWED_EVENTS` 与 openapi enum 已同步剔除，本表曾漏删，由 `verify-tracking.py` 三方一致性门禁拦下。

> `agent_second_created` 是最强的扩张信号——它同时验证定价成立与产品有用。

### 2.6 异常（3 个）

| 事件名 | 触发时机 | 关键属性 |
|---|---|---|
| `error_occurred` | 前端/接口错误 | `surface`, `error_type`（**不含错误详情与堆栈**） |
| `model_fallback_triggered` | 模型降级 | `from_model`, `to_model`（**不含调用内容**） |
| `key_invalid_detected` | 密钥失效 | `provider` |

---

## 三、禁记属性（黑名单，与白名单同等强制）

| 禁记项 | 原因 |
|---|---|
| IP 地址 | 隐私承诺 |
| User-Agent | 可识别设备 |
| **prompt 全文 / 工具返回全文 / 文档内容 / 检索到的 chunk 原文** | P0 承诺「不记录模型调用内容」 |
| 文件名 | 客户业务信息 |
| 金额以外的支付信息 | 合规 |
| 任何形式的个人身份信息 | 合规 |

---

## 四、口径计算说明（供 Spec 引用）

| 判据 | 计算口径 | 数据来源 |
|---|---|---|
| **TCR（按岗位组）** | 分子 = `task_completed` 数；分母 = 全部任务数。**软阈值拉人后完成不计入分子** | 上述事件 |
| **HITL** | `task_escalated_to_human` 数 ÷ 任务总数 | 上述事件 |
| **熔断率** | `task_circuit_broken` 数 ÷ 任务总数，**计入失败** | 上述事件 |
| **信任闭环指标** | `task_escalated_to_human` 与 `escalation_resolved` 配对计数。**禁止硬编码、禁止凑数、禁止无数据时编造** | 上述事件 |
| **激活率** | 同时触发 `first_run_completed` + `first_report_viewed` 的用户数 ÷ 新用户数 | 上述事件 |
| **成本准确度** | **不埋点**，直接从 `usage_records` 算「预估 vs 实际」 | 数据表 |

---

## 五、需要架构师在 Spec 中落地的三点

1. **后端白名单实现**：`trackEvent` 接口只接受本文档第二节的事件名，超出即丢弃并计入告警指标
2. **RLS 与保留期**：事件表走租户隔离，180 天自动清理
3. **端到端断言**：owner 用量接口递归搜索响应 JSON，断言无 `token` / `model` / `duration` key（架构 ADR-017 已提出）

---

## 六、判据 7 的流程依赖（非埋点，但需 Spec 落实）

**「成本不可预期投诉占比 = 0」这条判据当前无采集路径，客服不打标则永远假通过。**

需要产品流程配合：
- 退款/投诉原因改为**结构化枚举**，须包含「成本不可预期」选项
- **该字段对客服不可编辑**（防止事后美化）
- 落地位置：客服 SOP，Phase 2 需同步给客服团队

**这是 7 条判据中唯一必须改产品流程才能满足的一条，Spec 里需要有对应条目，否则上线后这条判据形同虚设。**