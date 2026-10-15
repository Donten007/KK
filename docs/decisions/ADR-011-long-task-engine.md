# ADR-011: F6 长任务引擎采用三层状态模型 + 四信号无进展检测

## Status
Accepted (2026-10-14)

## Background

PRD §7.3 F6「长任务引擎」是全产品最大技术风险：RICE 最低分（1.69）却是 P0。PM 的判断正确——没有它，产品退化成 Manus，会完整重演 Manus 的全部差评（半成品交付、死循环烧额度）。

竞品教训必须正面回答：

| 竞品 | 失败模式 | 我们必须做到 |
|------|---------|-----------|
| AgentGPT | 25 循环固定天花板，"需要 40 步推理的任务只能停在 25" | **无静默步数上限** |
| Manus | 无限循环持续扣费（有案例烧掉 88,000 额度） | **无进展检测熔断** |
| Manus | 长任务重复步骤、丢失进度、交付不完整 | **断点续跑 + 步骤幂等** |

PM 在需求中给出了三个候选方案（事件溯源 / 检查点快照 / 状态机 + 幂等写入），要求我选一个。**这个问题的前提是错的——三者不是互斥选项，而是解决三个不同层面的问题。**

核心洞察：**断点续跑要恢复的是「执行位置」，用户看到的是「业务步骤」，费用归集的是「业务步骤」。执行粒度与业务粒度不同，必须分开建模。**

## Decision

**采用三层状态模型，而非三选一。**

```
+--L3业务层: task_steps 表-----------------------------------------+
|  业务步骤状态机: pending/running/succeeded/failed/skipped        |
|  消费者: F4 每日汇报、费用归集、用户可见的"卡在第 N 步"          |
|  粒度: 业务可读（"读取竞品页面 3/10"）                           |
+----------------------------------------------------------------+
+--L2 执行层: LangGraph Checkpointer -------------------------------+
|  图节点状态快照 + 增量delta, schema: langgraph_checkpoints      |
|  消费者: 崩溃恢复、interrupt/resume                              |
|  粒度: 图节点（"fetch_url" / "parse" / "llm_decide"）           |
+----------------------------------------------------------------+
+--L1 正确性层: 幂等键---------------------------------------------+
|  task_steps.unique(goal_id, step_ordinal)                       |
|  L2 checkpoint 写入同样幂等                                      |
|  消费者: 崩溃重放时的副作用去重                                   |
+----------------------------------------------------------------+
```

**同时采用四信号无进展检测**（替代固定步数上限），详见 §3。

## Alternatives Considered

### 方案 A：纯事件溯源（Event Sourcing）

**评分：1.5 / 5**

每次从事件流重放重建全部状态。

| 维度 | 评分 | 依据 |
|------|------|------|
| 可审计性 | 5 | 最强，天然全审计 |
| 恢复正确性 | 2 | **重放需重跑副作用**。LLM 调用不确定，必须已缓存结果 |
| 恢复成本 | 2 | 随步数线性增长。40 步任务重放要重跑 40 次校验 |
| 实现复杂度 | 2 | 需要完整的 event store + 投影层 |
| 与 LangGraph 重叠 | 1 | LangGraph Checkpointer 本身就是事件溯源的工程实现 |

否决理由：**用自研 event store 去重新实现 LangGraph Checkpointer 已有的能力**，且实现得更差。这是典型的重复造轮子。

### 方案 B：纯检查点快照

**评分：2.5 / 5**

只有快照，无业务步骤概念。

否决理由：**无法支撑 F4 汇报与费用归集**。「今天做完了 1-24 步，卡在第 25 步」这个表述需要业务步骤级的状态和序号，快照里只有图节点，用户看不懂「`parse` 节点完成」是什么意思。**这是 PRD 验收标准里的硬要求（汇报用人的语汇，禁用 Agent/节点术语）。**

### 方案 C：纯状态机 + 幂等写入

**评分：3 / 5**

只有业务状态机，无执行层快照。

否决理由：**恢复精度不足**。业务状态机知道「第 25 步 started」，但不知道图执行到哪个节点的中间状态（如已 fetch 但未 parse 的临时产物、LLM 的中间推理链）。重启后只能从第 25 步整步重跑，而非精确续跑。

### 方案 D：三层状态模型（选中）

**评分：4.5 / 5**

| 维度 | 评分 | 依据 |
|------|------|------|
| 恢复精度 | 5 | L2 精确到图节点增量 |
| 用户可读性 | 5 | L3 业务可读，直接喂F4 汇报 |
| 成本归集 | 5 | L3 按步骤归集，粒度与用户认知一致 |
| 实现成本 | 4 | L2 复用LangGraph（ADR-007），L3 是普通业务表约 400 行 |
| 概念复杂度 | 3 | 三层需向团队讲清（本文档即为交付） |

## 详细设计

### 1. 数据模型

```sql
-- L3 业务层：用户可见的步骤
CREATE TABLE task_steps (
  goal_id        UUID NOT NULL REFERENCES goals(id),
  step_ordinal   INT  NOT NULL,          -- 1-based，用户可见的序号
  title          TEXT NOT NULL,          -- 业务语言："读取竞品页面 3/10"
  status         TEXT NOT NULL,          -- pending/running/succeeded/failed/skipped
  output_ref     TEXT,                   -- 对象存储 key 或 NULL
  cost_cents     INT  NOT NULL DEFAULT 0,
  model_id       TEXT,
  started_at     TIMESTAMPTZ,
  ended_at       TIMESTAMPTZ,
  error_code     TEXT,                   -- 枚举，不存原始异常全文
  PRIMARY KEY (goal_id, step_ordinal)    -- 幂等键
);

-- L1 正确性层：产出物登记表，用于无进展检测
CREATE TABLE task_artifacts (
  goal_id        UUID NOT NULL,
  artifact_id    UUID NOT NULL,
  step_ordinal   INT  NOT NULL,
  kind           TEXT NOT NULL,          -- file/row/record/http_call
  content_hash   TEXT NOT NULL,          -- 内容哈希，用于识别"改了又改回"
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (goal_id, artifact_id)
);
```

**`task_steps` 的 PRIMARY KEY 就是幂等键**。重放时 `INSERT ... ON CONFLICT DO NOTHING`，天然去重。

**为什么 `content_hash` 必要**：LLM 可能反复重写同一份文件。产出物数量在增加，但内容完全没变——如果只看数量会误判为有进展。用哈希才能识别"改了又改回原样"这种空转。

### 2. 无进展检测：四信号融合

PM 要求「连续 N 步无状态变化即判定卡死」。**单一信号不够，会误杀正常任务**。四信号分层：

| 信号 | 定义 | 判定强度 | 防的是什么 |
|------|------|---------|-----------|
| S1 重复工具序列 | 最近 K=5 步的**工具名+参数**签名序列哈希命中曾出现的窗口 | **确定性，立即熔断** | AgentGPT 式死循环 |
| S2 产出物增量 | `Δartifacts = 本步新增 artifact 数` | 强（可激进） | "改了又改回"的空转 |
| S3 外部副作用 | 连续步骤无任何外部 API 写入/文件产出 | 中（需宽松） | 假忙：反复重规划 |
| S4 状态指纹 | `hash(sorted(artifact_ids) + steps状态摘要)` | 弱（仅辅助） | 单信号易骗过 |

> **【重要修正，2026-10-15】** S1 的「工具调用签名」**必须包含归一化参数摘要，不能只含工具名**。
>
> 原设计签名仅含 `tool_name`，会导致「下载 50 个竞品页面」（`fetch_url → parse_html` 交替）这类**合法的周期性工作**在第 5 步就哈希命中被误杀。
>
> 修正后签名 = `tool_name(归一化参数)`，其中 `url`/`page`/`index`/`offset`/`id` 等**循环索引参数保留原值**（区分「循环推进」与「原地打转」正是靠它们），内容参数用哈希。
>
> 修正后 S1 从「零误判」降级为「误报极低」，**因此 F6-lite 必须同时包含 S2 作为第二道防线**，不能只靠 S1。详见 [ADR-016](ADR-016-icon-gate-and-s1-fix.md)。

```python
# app/agents/progress_guard.py
@dataclass(frozen=True)
class ProgressVerdict:
    should_continue: bool
    level: str# "ok" | "soft_pause" | "circuit_break"
    reason: str           # 机器可读，进审计
    user_message: str     # 业务语言，进"我停下来过"板块

async def evaluate(
    goal_id: UUID,
    steps: list[StepSnapshot],
    template: JobTemplate,   # 提供 expected_idle_steps
) -> ProgressVerdict:
    idle_n = template.expected_idle_steps   # 岗位级可配，默认 5
    soft_n = idle_n                          # 软阈值：等于岗位预期
    hard_n = idle_n * 2# 硬阈值：两倍岗位预期

    # S1 确定性死循环——签名(含参数)完全一致才熔断，误报极低
    if _has_repeated_tool_window(steps, k=5):
        return ProgressVerdict(False, "circuit_break", "repeated_tool_sequence",
                               user_message="我一直在重复做同一件事，已经停下来问你了。")

    # S2 产出物无增量
    if _consecutive_idle(steps, lambda s: s.delta_artifacts) >= hard_n:
        return ProgressVerdict(False, "circuit_break", "no_new_artifacts",
                               user_message=f"我卡在第 {steps[-1].ordinal} 步，"
                                            f"已经停下。前 {steps[-1].ordinal - 1} 步的成果都保留着。")

    # 软阈值——不熔断，拉人。这是 HITL 的正确用途
    if _consecutive_idle(steps, lambda s: s.delta_artifacts) >= soft_n:
        return ProgressVerdict(False, "soft_pause", "uncertain_progress",
                               user_message=f"我在第 {steps[-1].ordinal} 步有点没底，"
                                            f"要我继续还是先停下？")

    return ProgressVerdict(True, "ok", "progressing", "")
```

**软阈值用 LangGraph `interrupt()` 实现**，复用审批流机制（ADR-009），不是新机制。用户回答"继续"则 `Command(resume=...)` 带一个 `idle_streak` 归零的计数器继续，最多允许 2 次连续软暂停（防止无限次问）。

### 3. 分层阈值与岗位参数

**关键设计：无进展阈值由岗位模板声明，不由系统写死。**

理由：不同岗位的"合理无产出步数"差异巨大。「下载 100 个竞品页面」每步产出物相同是正常的（N=100）；「读一份 Excel」第 3 步没产出就是卡死。

```yaml
# job_templates 表新增字段
expected_idle_steps: 5# 默认 5，岗位可覆盖
expected_total_steps: 12       # 用于步骤数预估
idempotent_ceiling: 40         # 非熔断用的软告警线，仅提示用户
```

F1 岗位模板库需要在配置模板中增加 `expected_idle_steps` 字段，**这是 PM 需要在 F1 里补的一条**。

### 4. 熔断的时机：必须同步

**熔断判定必须在下一步 LLM 调用之前完成，不能等模型返回。**

PRD 验收标准明确「不产生熔断后的额外费用」。若等模型返回再判定，熔断时那一次的 token 已经花了——且死循环场景下每轮都是完整 LLM 调用，这是漏损最大的一处。

```python
# 图的每个节点入口处，而非出口
async def guarded_node(ctx):
    verdict = await progress_guard.evaluate(ctx.goal_id, ...)
    if verdict.level == "circuit_break":
        raise CircuitBroken(verdict.reason, verdict.user_message)  # 不再调 LLM
    if verdict.level == "soft_pause":
        interrupt_for_human(verdict.user_message)
    return await real_node(ctx)
```

### 5. 检测状态必须落盘

**检测窗口状态（`idle_streak` / `seen_tool_windows`）必须随 checkpoint 持久化。**

否则崩溃重启后窗口归零，死循环会重复触发 N 次才熔断——每轮都是真金白银。必须存在 `task_steps` 的一行元数据或独立的 `goal_progress_state` 表里。

## F6 Effort 重估与分期建议

### Effort=8 人月是否合理：偏高 40-60%

分解如下（我的架构 §12.1 已把基础设施算进Phase 2-3 的 6-8 人月）：

| 工作项 | PM 估算归属 | 实际归属 | 人月 |
|--------|-------------|---------|------|
| 断点续跑（Checkpointer） | F6 | **已在 Phase 2-3 基础设施预算内**（ADR-007） | 0（已计） |
| 事件流 / SSE进度推送 | F6 | **已在基础设施预算内**（ADR-002/008） | 0（已计） |
| `task_steps` 业务状态机 + 汇报对接 | F6 | F6 增量 | 1.0 |
| 无进展检测（四信号 + 阈值调参） | F6 | F6 增量 | **1.5**（含调参，非纯编码） |
| 步骤数预估 | F6 | F6 增量 | 0.5 |
| 中止 + 协作式取消 | F6 | F6 增量 | 0.5 |
| 部分成功语义 + 汇报 | F6 | 与 F4 重叠 | 0.5 |
| 幂等键贯穿 | F6 | F6 增量 | 0.5 |
| **F6-full 合计** | 8 | | **5.0** |
| 岗位模板步骤定义（F1 部分） | 未计入 | F1 | 0.5 |

**结论：Effort=8 人月偏高约 40-60%。F6-full 合理区间 4.5-5.5 人月。** 但这个"降低"有水分——无进展检测的**阈值调参**是真功夫，需要真实任务数据反复调，MVP 阶段只能给初值。建议对 PM 说 **5-6 人月**（含调参余量），而不是 4.5。

### 建议：分期，不降级

PM 的降级方案是「AI 生成执行方案 + 人工逐步确认」。**这个方案技术上代价很小（复用 `interrupt`，1-2 人周），但产品代价极大：**

| 维度 | 影响 |
|------|------|
| HITL 率 | 从 ≤2% 变成 **100%** —— **直接违反 PRD §8.4 的 Go/No-Go 判据** |
| 产品定位 | 「雇 AI 员工」变成「AI 帮你想，你自己做」 |
| ROI 论证 | 567% ROI 基于自主完成，人工确认后 ROI 崩塌 |
| 定价论证 | ¥899/月 对标实在智能 1-2 万/年/人的逻辑不成立 |

**所以我的建议是「分期」而非「降级」：**

| 方案 | 内容 | 人月 | 覆盖 PRD 验收标准 |
|------|------|------|---------|
| **F6-lite**（MVP 用） | 断点续跑 + 中止 + 步骤预估 + 简版熔断（仅 S1 重复工具序列检测） | **1.5-2** | 覆盖「40 步崩，第 26 步续跑，成果费用保留」+「熔断不产生额外费用」两条核心验收 |
| **F6-full**（Phase 2） | 四信号融合 + 软阈值人工确认 + 岗位级阈值调参 | 3-4 | 覆盖全部，含「我停下来过」的可信度 |

**关键判断：F6-lite 能挡住 Manus 的两类差评**（半成品交付 + 死循环烧额度），因为 S1 用「工具名 + 归一化参数完全一致」作判据，能抓住 AgentGPT 式的真死循环且误报极低（但非数学证明为零，**仍需 S2 兜底**）。S3/S4 是防更隐蔽的“假忙”，可以等真实数据。

**绝不能砍的是断点续跑。** 那是与 Manus 差评正面对撞的能力，砍它等于承认自己是 Manus。

### MVP 岗位难度递进的技术背书

PM 的上线顺序（文档/表格类先行，电商订单录入最后）对 F6 是**有利的**，我给出技术依据：

| 岗位类型 | 步骤数 | 外部副作用 | 熔断风险 | F6-lite 够用? |
|---------|-------|-----------|---------|------------|
| 竞品监控日报 | 3-8 | 低（只读） | 低 | 是 |
| 周报汇总 | 3-6 | 低（只读 + 生成） | 低 | 是 |
| 发票信息核对 | 8-15 | 中（结构化输出） | 中 | 是 |
| 客户跟进催办 | 5-12 | 中（可能写 CRM） | 中 | 是 |
| 电商订单录入 | 20-40 | **高（外部系统写入）** | **高** | **需 F6-full** |

**结论：前 4 个岗位 F6-lite 足够，第 5 个（电商订单录入，决定成败的那个）才需要 F6-full。** 这给了我们一个天然的推广节奏：MVP 用 F6-lite 上线拿真实数据，Phase 2 在做电商岗位时补 F6-full。

## Related ADRs

- ADR-007（Goal 断点恢复）—— L2 层实现
- ADR-009（员工调度 interrupt）—— 软阈值复用 interrupt 机制
- ADR-010（治理层）—— 费用归集依赖 L3 业务层
- ADR-011（本文件）—— L3 业务层 + 无进展检测

## Verification

**存在性核验**：

```bash
psql -c "\d task_steps"   # PRIMARY KEY (goal_id, step_ordinal)
psql -c "\d task_artifacts"
```

**端到端验证步骤**：

1. **断点续跑核心用例**：
   - 造 40 步任务，执行到第 25 步后 `SIGKILL` worker
   - 断言：`task_steps` 有 24 行 `succeeded` + 1 行 `running`
   - 断言：重启后从第 26 步继续，`task_steps` 最终 40 行
   - 断言：第 1-24 步的 `cost_cents` **没有变化**（不重复计费）
2. **幂等性（阻断级）**：
   - 在「业务写入成功、checkpoint 未落盘」时刻崩溃
   - 断言：重启后该步不产生重复业务数据（`COUNT(*) = 1`）
   - 断言：`task_artifacts` 无重复 artifact_id
3. **S1 确定性死循环**：
   - 注入一个反复调用同一工具序列的图
   - 断言：连续 5 步签名(工具名+参数)完全一致后**立即熔断**
   - 断言：熔断发生在**下一次 LLM 调用之前**（用调用计数验证）
4. **S2 空转识别**：
   - 注入"反复重写同一文件"的任务
   - 断言：`artifact` 数量在增加但 `content_hash` 相同
   - 断言：系统在 `hard_n` 步内识别为空转并熔断
5. **误杀测试（反向验证，关键）**：
   - 跑「下载 50 个竞品页面」任务，每步产出物不同
   - 断言：**全程不触发熔断**
   - 这条比熔断本身更重要——误杀率高的熔断比没有熔断更糟（用户会失去信任并关闭功能）
6. **软阈值人工确认**：
   - 触发 `soft_pause`
   - 断言：run 状态 `waiting_human`，用户收到「我在第 N 步有点没底」
   - 用户回"继续"后从暂停点继续，`idle_streak` 归零
   - 断言：连续 3 次软暂停后强制熔断，不允许无限问
7. **检测状态持久化**：
   - 在 `idle_streak=4`（距熔断 1 步）时崩溃重启
   - 断言：`idle_streak` 从 4 恢复而非归零，**下一步即熔断**
   - 若归零则说明死循环要重复触发 N 次，是严重漏损
8. **部分成功仍产出汇报**：
   - 造 10 步任务，第 7 步不可恢复失败
   - 断言：前 6 步成果保留，汇报产出，「我停下来过」板块说明卡在第 7 步
   - 断言：**不丢弃全部成果**
9. **中止**：
   - 执行中用户点中止
   - 断言：协作式取消（`asyncio` task cancel + 状态落盘）
   - 断言：已完成步骤保留，**已完成部分不扣费**
10. **岗位级阈值**：
    - 同一条检测逻辑，分别用 `expected_idle_steps=5` 和 `=100` 的岗位跑
    - 断言：熔断触发步数随参数变化，**证明阈值确实由岗位控制而非硬编码**

第 2、5、7 条为阻断级。第 5 条（误杀测试）尤其重要——**熔断系统的误报率必须实测，这是产品能否被信任的关键**。