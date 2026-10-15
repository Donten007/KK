# ADR-017: 中止态独立建模 + 事件可见性分级 + 用量接口按视图分离

## Status
Accepted (2026-10-14)

## Background

设计师在 UIUX §7.5.1/§7.5.2 交付了两项交互层规范，PM 在 PRD 侧补充了三条接口层约束。本 ADR 固化其中影响架构的部分，并**修正一处已被证伪却被写入 PRD 的引用**。

三个来源的输入：

| 来源 | 输入 |
|------|------|
| 设计师 | `stopping` 独立状态、事件三级可见性（owner/admin 分级） |
| PM（转设计部） | owner 视图接口层不传 token 字段（AC-14b）、埋点拆分 |
| PM | owner/admin 用量接口是同一 endpoint 还是两个（待确认） |

## Decision

### 一、中止态 `stopping` 独立建模（不是 `running` 的子状态）

采纳设计师的状态机：

```
queued → running → stopping → cancelled
       └────────────→ completed  （中止生效前恰好跑完）
```

**后端实现要求**：

| 项 | 要求 |
|----|------|
| 状态枚举 | `goal_status` 增 `stopping`（**不是 flag，是独立状态**） |
| 中止接口幂等 | **重复 cancel 必须返回同一状态，不报错**。UI 的 disabled 按钮是最后防线但不能是唯一防线（用户可能开两个标签页、或网络重试） |
| 超时兜底 | `stopping` 最长 5 秒，超时降级为 `cancelled` + 提示「已请求中止，后台正在收尾；已完成步骤已保存」。**保证 UI 永不卡在中间态** |
| 已完成步骤 | 保持原样，不回滚不置灰，**且不扣费**（对应 PRD「已完成部分不扣费」） |
| 边界三种 | 恰好完成 → 直接 `completed` 不闪 `stopping`；`queued` 态中止 → 零延迟 `cancelled`；已 `cancelled` → 幂等返回 |

**协作式取消的实现顺序**（不可颠倒）：

```
1. API 收到 cancel → 立即置 status=stopping → 返回 200（不等任务真停）
2. 向 worker 发协作式取消信号（asyncio task cancel / SIGTERM）
3. worker 在步骤边界检查取消标志 → 保存 checkpoint → 置 cancelled
4. 若 5s 内未完成 → 巡检器强制置 cancelled
```

**关键约束**：第 1 步必须在第 2 步之前。否则用户点中止到看到反馈有 1-3 秒延迟，UI 无法显示 `stopping` 态，用户会以为按钮坏了重复点。

### 二、事件可见性分级：`visibility` 字段，**默认 admin**

采纳设计师的三级分界（「这件事老板需不需要知道？」）：

| 级别 | 内容 | UI 呈现 |
|------|------|--------|
| L1 主叙事（owner 可见） | 任务级里程碑：`task_started`/`step_completed`/`task_completed`/`task_failed`/`needs_human_input` | 时间轴一行摘要 |
| L2 细节（owner 可见，折叠） | 单步输入输出、耗时、命中文档名：`tool_called`/`retrieval_hit`/`file_written` | 折叠节点 |
| **L3 审计（仅 admin）** | 原始 prompt / 完整响应体 / 重试记录 / token 明细 | **owner 界面绝不出现** |

**架构实现：事件表增 `visibility` 字段，默认 `'admin'`**

```sql
ALTER TABLE goal_events ADD COLUMN visibility TEXT NOT NULL DEFAULT 'admin';
-- 枚举：admin | owner
```

**默认值方向是这条设计的核心**：新增事件类型时若忘记标 `owner`，会**默认落在 admin 侧**（安全），而不是默认泄漏给老板。

**L1 禁止项**（对齐设计师 §8.1「禁止系统日志语汇」）：L1 事件不得含 `[INFO]` / `elapsed=` / token 数。

**SSE 端点按调用方角色过滤**：`owner` 只推送 `visibility='owner'` 的事件；`admin` 推送全部。**过滤在服务端做，不依赖前端过滤。**

### 三、用量接口：**两个独立 endpoint**（回答 PM 的最后一问）

PM 倾向两个独立 endpoint，我确认这个选择，理由比 PM 说的更强：

| 方案 | 契约清晰性 | TS 类型分离 | 泄漏风险 |
|------|-----------|------------|---------|
| 同一 endpoint 按角色 oneOf | **OpenAPI 表达吃力**，前端类型退化为联合类型，每次访问都要判别 | 弱 | 中 |
| **两个独立 endpoint** | 各自 schema 单一清晰 | **天然分离** | **低——owner 的 schema 里根本没有 token 字段** |

**决定性理由**：PM 已经定了原则「承诺的不只是不记录，而是连返回给老板的接口里都不出现」。**如果两个视图共用一个 endpoint，token 字段就在 owner 的响应 schema 里**，只是被 controller 剔除——这与「schema 里不存在」不是一个强度。用两个 endpoint，**契约层本身就杜绝了泄漏**，符合 PM 说的「从契约层就区分开」。

```
GET /api/v1/usage/summary      → OwnerUsageSchema   { task_count, cost_cents, breakdown_by_job }
                                                    （无 token / 无 model / 无 duration）
GET /api/v1/settings/usage     → AdminUsageSchema   { ..., input_tokens, output_tokens, model, ... }
```

**OpenAPI 用两个独立 schema 表达**，前端 `openapi-typescript` 生成的类型天然分离，owner 组件的 TS 类型里访问 token 会直接编译报错。

**落库侧配套**：admin schema 的数据来自 `usage_records`；owner schema 的数据来自 `tasks` + `cost_ledger` 聚合。**owner 口径不读 token 表**，从数据源上就断开。

### 四、埋点拆分确认

`report_viewed` → `owner_report_viewed` / `admin_usage_viewed`。同意，不拆无法衡量老板是否真在用汇报页（PRD §8.4 留存判据依赖它）。

## 重要修正：AC-17 的引用依据已被证伪

PM 在 AC-17（误杀测试阻断级）中写「理由用了你的原话：**F6-lite 的 S1 是确定性零误判**，故该测试在 MVP 即适用」。

**这个引用必须撤回。** 我在 ADR-016 中已证明该说法是错的：

> 若签名仅含工具名，「下载 50 个竞品页面」（`fetch_url→parse_html` 交替）在**第 5 步即哈希命中被误杀**。

**AC-17 的结论（测试在 MVP 即适用）仍然正确，但理由要改**：

| 项 | 内容 |
|----|------|
| 错误理由（已撤回） | 「S1 是确定性零误判，所以测了个设计上不会失败的东西」 |
| 正确理由 | **S1 收窄后仍有非零误判率**（误杀条件收窄到「工具名+参数完全一致重复 5 次」，但非数学证明为零）；**且 S2 是 F6-lite 新增信号，阈值需实测调参**。因此误杀测试在 MVP 必需 |

**且 AC-17 必须补一条**：误杀测试需验证**修正前后的行为差异**——用仅含 `tool_name` 的旧签名跑「下载 50 页面」应当误杀，用新签名应当放行。**否则测试无区分力，测了也白测。**

**这条必须在 Phase 2 前改，否则会误导开发者认为 S1 天然无误杀风险而不去正确实现参数签名。**

## Consequences

### 正面

- **中止体验不会被误判**：`stopping` 独立状态 + 幂等 cancel + 5s 超时兜底，三层保证 UI 不卡中间态、不重复提交
- **事件可见性默认安全**：新增事件忘记标 owner 时默认落 admin，不会意外泄漏给老板
- **token 泄漏在契约层被杜绝**：两个独立 endpoint + 两个 OpenAPI schema，owner 的 TS 类型里根本没有 token 字段，访问即编译报错
- **数据源层面断开**：owner 口径不读 token 表，不是「读了但不给」而是「根本不读」

### 负面

**七条必须落进 Spec 的约束**：

1. **`stopping` 是独立状态不是 flag**。`goal_status` 枚举含 `stopping`；禁止用 `is_cancelling` 布尔标志代替
2. **cancel 接口必须幂等**，重复调用返回同一状态不报错。必须支持双标签页场景
3. **cancel 必须先置 `stopping` 再发取消信号**，顺序不可颠倒（否则 UI 无法显示中间态）
4. **`stopping` 必须有 5s 超时兜底**，由巡检器强制收敛为 `cancelled`。不允许 UI 永久停在中间态
5. **`goal_events.visibility` 默认 `'admin'`**，新增事件默认不面向老板。SSE 端点按角色在服务端过滤
6. **两个独立 endpoint + 两个独立 OpenAPI schema**，禁止用 oneOf 在同一 endpoint 表达。owner schema 内不得出现 token/model/duration 字段（连 nullable 都不行）
7. **owner 口径的数据源不读 token 表**，从聚合路径上断开，不是「读了再剔除」

**其他负面**：

- **两个 endpoint 意味着两次请求**（若同一页面需两者）。但老板页与管理员页本就是两个独立页面，各自只需一个 endpoint，**实际不产生额外请求**。PM 说的「省一次请求」不成立
- **`visibility` 字段需要评审纪律**：新事件若要面向老板，必须显式改默认为 `owner`，而这个动作需要 review 拦一道（防止把带 prompt 内容的错误标成 owner）
- **AC-17 的引用需在 Phase 2 前修正**，否则误导实现者

## Related ADRs

- ADR-009（员工调度 interrupt）—— `stopping` 与 interrupt 的关系
- ADR-010（治理层）—— §9.6 可观测性数据边界，本 ADR 是其在接口层的延伸
- ADR-011（长任务引擎）—— AC-17 引用修正
- ADR-015（指标口径）—— `owner_report_viewed` / `admin_usage_viewed` 拆分
- ADR-016（图标门禁 + S1 修正）—— 设计师本轮引用的图标已实包验证通过

## Verification

**存在性核验**：

```bash
npm pack lucide-react@1.57.0 && tar -xzf lucide-react-1.57.0.tgz
grep "declare const CircleDashed:" package/dist/lucide-react.d.ts   # 已验证 OK
psql -c "\d goal_events"   # 需含 visibility NOT NULL DEFAULT 'admin'
```

**端到端验证步骤**：

1. **stopping 独立状态（阻断级）**：
   - 发起 cancel，断言：`status` 变为 `stopping`（**不是 `running` + flag**）
   - 断言：接口在 1 秒内返回 200（不等任务真停）
   - 断言：最终收敛到 `cancelled`，已完成步骤保留且不扣费
2. **cancel 幂等（阻断级）**：
   - 对同一 taskId 连续发 3 次 cancel
   - 断言：**全部返回 200 且状态一致，无报错**
   - 断言：后端只发出一次取消信号
3. **stopping 超时兜底（阻断级）**：
   - 构造一个不响应取消信号的 worker
   - 断言：5 秒后巡检器强制置 `cancelled`
   - 断言：**UI 永不卡在 `stopping`**
4. **边界三种**：
   - 任务恰好在 cancel 生效前完成 → 断言：直接 `completed`，**不闪 `stopping`**
   - `queued` 态 cancel → 断言：零延迟 `cancelled`
   - 已 `cancelled` 再 cancel → 断言：幂等返回
5. **事件可见性（阻断级）**：
   - 造一个 `visibility='admin'` 的事件（如 `raw_prompt`）
   - 以 owner 身份订阅 SSE，断言：**收不到该事件**
   - 以 admin 身份订阅，断言：能收到
   - **断言：`goal_events` 表中 `visibility` 默认为 `'admin'`**（新插入事件不显式指定时）
6. **token 不泄漏（阻断级）**：
   - 调用 `GET /api/v1/usage/summary`（owner），断言：响应 JSON **递归搜索无 `token` 键**
   - 断言：OpenAPI 中 `OwnerUsageSchema` 的 properties **不含** token/model/duration
   - 前端用 `openapi-typescript` 生成类型后，断言：owner 组件访问 token **编译报错**
7. **owner 口径数据源**：
   - 断言：owner summary 的查询 SQL **不 join `usage_records` 的 token 字段**
8. **AC-17 引用修正**：
   - 断言：Phase 2 Spec 中误杀测试的理由**不含**「S1 是确定性零误判」
   - 断言：误杀测试含「修正前后行为差异」用例（旧签名应误杀、新签名应放行）

第 1、2、3、5、6 条为阻断级。第 6 条的递归搜索断言可做成自动化脚本，防止后续有人在 owner schema 里加回token 字段。