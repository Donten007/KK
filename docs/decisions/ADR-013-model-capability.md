# ADR-013: 模型能力元数据以厂商 API 为准 + 硬编码能力标签表双层校验

## Status
Accepted (2026-10-14)

## Background

PRD §7.3 F2 的失败边界里有一条：

> 模型不支持所选能力（视觉、工具调用）—— **前置校验，而不是跑到一半失败**

F2 具体要求 ④：

> 模型能力差异必须在 UI 上明示（不支持视觉/长上下文的模型要做任务前置校验，而不是跑到一半失败）

PM 的问题：**模型能力标签怎么定义和校验？硬编码清单还是按模型元数据自动判断？**

这个问题的难点在于能力信息是**分散且不完整**的：

- 视觉能力：OpenAI 有明确字段，但 Anthropic/智谱的字段命名各不相同
- 工具调用能力：几乎所有厂商都支持，但支持的**参数量/嵌套深度**不同
- 上下文长度：各家 API 返回的 metadata 常常缺失或不准

**不能只靠任一单一来源**，必须双层。

## Decision

**双层：能力标签表（数据库，硬编码但可运营）+ 厂商 API metadata 探测（运行时，自动但仅作补充）。**

**判定优先级（严格顺序）**：

```
1. 数据库能力标签表（显式声明，最高权威）
   ↓ 无记录时
2. 厂商 API metadata 探测（自动）
   ↓ 无记录时
3. 保守默认（假设不支持，要求用户确认）
```

**关键原则**：**能力不足时必须在执行前阻断，不允许"跑到一半失败"**。这直接对应 PRD 的验收标准。

**能力维度（本项目需要的最小集）**：

| 能力 key | 含义 | 影响的岗位 |
|---------|------|-----------|
| `vision` | 支持图像输入 | 发票信息核对（拍照发票）、电商订单录入（商品图） |
| `tool_use` | 支持函数/工具调用 | **全部 5 个岗位**（F1 岗位全是工具驱动） |
| `long_context` | 上下文 > 32K tokens | 周报汇总（大量文本聚合） |
| `json_schema` | 支持结构化输出（strict schema） | 发票信息核对（字段抽取）、电商订单录入 |
| `streaming` | 支持流式 | 全部（长任务进度） |

## Alternatives Considered

### 方案 A：纯硬编码能力表（代码常量）

**评分：2.5 / 5**

| 维度 | 评分 | 依据 |
|------|------|------|
| 准确性 | 5 | 人工核对过，最准 |
| 新模型上市 | 1 | **需发版才能支持新模型**。模型迭代极快（周级），这是致命缺陷 |
| 运行时开销 | 5 | 无网络调用 |
| 可运营性 | 1 | 改能力要改代码 + 发版 |

否决理由：**新模型支持滞后**是硬伤。客户拿到新模型想用，我们说"等我们下个版本"，这在竞争上是自杀。

### 方案 B：纯运行时探测厂商 API

**评分：2 / 5**

| 维度 | 评分 | 依据 |
|------|------|------|
| 新模型上市 | 5 | 自动支持 |
| 准确性 | 2 | **metadata 常常缺失或不准确**。上下文长度字段很多厂商不返回；视觉能力无标准字段 |
| 运行时开销 | 2 | 需调用厂商 API，有延迟与失败率 |
| 探测定成本 | 3 | 不能对每次任务都探测（慢且花钱），需缓存 |

否决理由：**metadata 不可靠**。且探测本身有成本（网络调用 + 可能被限流）。更严重的是探测失败时的行为不确定。

### 方案 C：双层（选中）

**评分：4.5 / 5**

| 维度 | 评分 | 依据 |
|------|------|------|
| 新模型上市 | 4 | 首次使用时探测并落库，之后缓存 |
| 准确性 | 5 | 人工标注优先，探测补充 |
| 运行时开销 | 4 | 探测结果缓存，TTL 24h，同模型只探一次 |
| 可运营性 | 5 | **改能力只需改数据库记录，不需要发版** |

## 详细设计

### 1. 能力标签表

```sql
CREATE TABLE model_capabilities (
  provider         TEXT NOT NULL,       -- openai/anthropic/deepseek/zhipu
  model_id         TEXT NOT NULL,       -- gpt-4o / claude-sonnet-4 / deepseek-chat
  vision           BOOLEAN NOT NULL DEFAULT FALSE,
  tool_use         BOOLEAN NOT NULL DEFAULT FALSE,
  long_context     BOOLEAN NOT NULL DEFAULT FALSE,
  json_schema      BOOLEAN NOT NULL DEFAULT FALSE,
  streaming        BOOLEAN NOT NULL DEFAULT TRUE,
  context_window   INT,                 -- 显式声明时优先
  source           TEXT NOT NULL,       -- manual/api_probe/unknown
  probed_at        TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, model_id)
);
```

**这张表在数据库而非代码里** —— 这是关键设计。新模型上市时，运营在后台填一行记录即可，**不需要发版**。

### 2. 三层判定实现

```python
# app/services/llm/capability_service.py
class CapabilityService:
    async def check(
        self, provider: str, model_id: str, required: list[str]
    ) -> CapabilityVerdict:
        caps = await self._get_caps(provider, model_id)

        missing = [c for c in required if not caps.get(c, False)]
        if missing:
            #保守默认：未知能力视为不支持（fail-closed）
            return CapabilityVerdict(
                can_run=False,
                missing=missing,
                user_message=(
                    f"{model_id} 不支持：{'、'.join(self._zh(c) for c in missing)}。"
                    f"请换一个支持的模型，或调整岗位配置。"
                ),
            )
        return CapabilityVerdict(can_run=True, missing=[])

    async def _get_caps(self, provider: str, model_id: str) -> dict:
        # L1: 查表
        row = await self.db.get_model_caps(provider, model_id)
        if row and row.source in ("manual", "api_probe"):
            return row.to_dict()

        # L2: 探测（缓存 24h）
        cached = await self.cache.get(f"caps:{provider}:{model_id}")
        if cached:
            return cached

        probed = await self._probe(provider, model_id)   # 调厂商 API
        await self.db.upsert_model_caps(
            provider, model_id, **probed, source="api_probe"
        )
        await self.cache.set(f"caps:{provider}:{model_id}", probed, ttl=86400)
        return probed

    async def _probe(self, provider: str, model_id: str) -> dict:
        """保守探测：任一测试失败即判为不支持"""
        result = {"vision": False, "tool_use": False,
                  "json_schema": False, "streaming": False,
                  "long_context": False, "context_window": None,
                  "source": "api_probe"}
        try:
            # streaming: 发一个极短请求看是否返回 stream chunk
            result["streaming"] = await self._probe_streaming(provider, model_id)
            # tool_use: 发一个带 tool 定义的最小请求
            result["tool_use"] = await self._probe_tool_use(provider, model_id)
            # vision: 发一个 1x1 像素 PNG（成本极低）
            result["vision"] = await self._probe_vision(provider, model_id)
            # json_schema: 发一个带 strict schema 的最小请求
            result["json_schema"] = await self._probe_json_schema(provider, model_id)
            # long_context + context_window: 不主动探测（成本高），
            # 用 model_id 启发式匹配已知长上下文模型
            result["long_context"], result["context_window"] = \
                self._infer_context(provider, model_id)
        except Exception:
            pass  # 探测失败 -> 全部保持 False（保守）
        return result
```

### 3. 校验时机：三个位置，不只配置时

PM 说「配置阶段就阻断」。**配置阶段校验不够**——用户配好岗位后，模型能力可能变化（降级/欠费/厂商限制），也可能用户直接跑单任务绕开岗位。

| 时机 | 动作 | 阻断? |
|------|------|------|
| 1. 岗位配置时 | UI 即时校验，显示缺失能力 | 是（不允许保存无效配置） |
| 2. 试跑/任务提交时 | 调度器校验（权威） | 是 |
| 3. 每个图节点执行时 | 校验该节点所需能力 | 是（但只影响该节点） |

**第 3 条的必要性**：单任务可能只用 `tool_use` 不需要 `vision`。第1 层校验按"整个岗位"的要求过严会阻塞合法任务。**必须按节点粒度校验**，这样"竞品监控日报"（不需要 vision）可以用不支持 vision 的模型跑，只在真正需要读图的节点才阻断。

```python
# 图节点声明所需能力
add_node("parse_invoice", parse_invoice, required_caps=["vision", "json_schema"])
add_node("fetch_page", fetch_page, required_caps=["tool_use"])
```

**降级策略**：模型被降级（厂商故障切换，ADR-011 §12 要求）到能力不足的备用模型时，**必须中止而非静默降级**。PRD 的可用性要求「模型厂商故障时自动降级到备用模型并明确告知用户已降级」——但若备用模型能力不足，**宁可不降级**：

```
if 备用模型能力满足:
    降级 + 标记 event: model_fallback_triggered + 推送告知
else:
    中止任务 + 标记 event: fallback_capability_insufficient
    + 汇报「我停下来过」板块说明
```

### 4. 岗位能力需求声明

F1 岗位模板需要声明所需能力（这是 PM 需要在 F1 补的第二条）：

```yaml
# job_templates 表新增字段
required_caps: ["tool_use", "json_schema"]
optional_caps: ["vision"]     # 有则更好，无则降级
```

## Consequences

### 正面

- **新模型支持不发版**：数据库加一行记录即可，运营可自助
- **判定准确**：人工标注优先，未标注的走探测
- **fail-closed**：能力未知时假设不支持，宁可拦截也不让用户跑到一半失败（这是 PRD 的硬要求）
- **节点粒度**：不因岗位整体能力要求过严而阻塞合法任务

### 负面

**必须写进 Spec 的五条约束**：

1. **能力判定必须 fail-closed**。探测失败/超时/异常**一律判为不支持**，绝不能fail-open（fail-open 会让用户跑到一半失败，直接违反 PRD 验收标准）
2. **探测必须低成本**。vision 探测用 1x1 像素 PNG；tool_use 探测用最小 tool 定义；`max_tokens=1`。**探测本身会产生费用，必须计入成本**（一次性，每模型约 ¥0.001）
3. **探测结果必须缓存 24h**。不能每次任务都探测——网络开销 + 限流风险
4. **`long_context` 不主动探测**。探测长上下文需要发长请求，成本高（一次可能 ¥0.5+）。用 model_id 启发式匹配已知长上下文模型
5. **降级必须检查能力**。厂商故障切换到备用模型前，**必须校验备用模型能力是否满足**，不满足则中止并告知，不可静默降级

**其他负面**：

- **`model_capabilities` 表需要运营维护**。人工标注的记录可能过期（模型被厂商下线/能力变更）。建议每月复核一次 `source='manual'` 的记录
- **探测失败率不可忽视**。欠费/限流时探测会失败 → 判定为不支持 → 用户困惑（"明明支持却说不支持"）。**必须在 UI 区分「确认不支持」与「探测失败，不确定」**，后者允许用户手动覆盖
- **允许用户覆盖判定**：企业客户可能用私有部署模型（不在我们的表里）。必须提供"我确认这个模型支持 XX 能力"的手动勾选，**但需记录到审计日志**（因为用户可能选错，导致跑到一半失败）

## Related ADRs

- ADR-010（治理层）—— 成本记录
- ADR-011（长任务引擎）—— 节点粒度能力校验
- ADR-006（前端）—— UI 明示缺失能力

## Verification

**存在性核验**：

```bash
psql -c "\d model_capabilities"
```

**端到端验证步骤**：

1. **PRD 验收标准逐条验证**：
   - 选不支持 vision 的模型跑需要读图的岗位 -> **配置阶段即阻断**，提示"该模型不支持图片识别"
   - 断言：任务**未进入执行**（无 LLM 调用产生）
2. **节点粒度校验**：
   - 用不支持 vision 的模型跑"竞品监控日报"（只需 tool_use）
   - 断言：**正常执行成功**（不被 vision 需求误阻塞）
3. **fail-closed**：
   - 模拟探测 API 超时/500
   - 断言：判定为**不支持**，任务被阻断
   - 断言：**不出现"探测失败但放行"的情况**
4. **新模型不发版支持**：
   - 插入一条 `model_capabilities` 记录（模拟新模型）
   - 断言：**无需重启/发版**，该模型立即可用
5. **缓存生效**：
   - 连续发起 10 个任务（同一模型）
   - 断言：厂商 API 探测只发生 1 次（缓存命中 9 次）
6. **降级能力检查**：
   - 主模型故障，备用模型不支持所需能力
   - 断言：**中止任务** + `fallback_capability_insufficient` 事件
   - 断言：**不静默降级**导致后续步骤失败
   - 反向：备用模型能力满足 -> 降级成功 + `model_fallback_triggered` 事件
7. **用户覆盖**：
   - 私有部署模型不在表中，用户手动勾选能力
   - 断言：可用+ 记入审计日志
8. **探测成本可接受**：
   - 断言：单模型首次探测费用 < ¥0.01（用 1x1 PNG + max_tokens=1验证）

第 1、3、6 条为阻断级。第 3 条尤其重要——**fail-open 会直接违反 PRD 的核心验收标准**。