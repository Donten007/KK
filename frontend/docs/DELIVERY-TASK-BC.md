# 任务 B + C 完成汇报 —— 核心页面 + BYOK 文案约束

```
verdict: pass
blocking: []
```

## 1. 交付证据

| 页面 | artifact_ref | 密度 | 要点 |
|---|---|---|---|
| 每日汇报 `/` | `src/components/report/daily-report-view.tsx` | 4 | 四板块固定顺序 + 空状态四套互不相同 |
| 岗位库 `/jobs` | `src/components/jobs/job-library-view.tsx` | 6 | 单卡布局，未写「先雇一个」 |
| 试跑结果 `/jobs/{id}/trial` | `src/components/trial/trial-result-view.tsx` | 4 | 全产品最松，员工口吻 |
| 登录/注册 `/login` | `src/app/login/page.tsx` | 6 | 反Hero：真实工作台预览 |

**四条路由全部构建成功**（`/`、`/login`、`/jobs`、`/jobs/[id]/trial`）。

## 2. 自检结果

```
lint        PASS   0 error
type-check  PASS   0 error
build       PASS   5 routes
verify:p0   PASS   8/8 门禁全绿
```

### P0 门禁从 6 项扩到 8 项

```
1/8 emoji as functional icon         PASS
2/8 bare hex in component code       PASS
3/8 forbidden bounce easing          PASS
4/8 AI template artifacts            PASS  (含左侧色条检测)
5/8 single file > 300 lines          PASS  (最大文件 185 行)
6/8 lucide icon name existence       PASS  (25 个图标名逐个核对真实导出)
7/8 BYOK forbidden words in UI copy  PASS  ← 新增
8/8 'Token' forbidden in owner pages PASS  ← 新增
```

第7/8 项是关键：它们扫描**用户可见文案**，且排除注释行——
门禁不能因为自己的说明文档报错，否则会被整体忽略（我在第 3 项上就踩了这个坑，已修）。

## 3. 四条最容易做错的产品约束 —— 逐条核对

### ① 成本下钻两层到底

| 要求 | 实现 | 位置 |
|---|---|---|
| 同页展开不跳页 | `useState` 展开，无 `Link` | `cost-breakdown-panel.tsx` |
| 禁止跳 `/settings/usage` | 代码中零引用 | — |
| 禁模型名/单价/调用次数 | 只渲染 `agent_name`/`cost_cents`/`task_count` | `cost-breakdown-list.tsx` |
| 密度恒为 4 | 行距宽松、无斑马纹、无表格 | 同上 |
| 零成本员工必须列出 | `Pause` + 「今天没有运行」，不折叠 | 同上 |
| 结论 body / 计量 mono+tabular 右对齐 | 结论句 `font-body` 20px；金额 `tabular` 右对齐 | `block-cost.tsx` |

**第 3 层「这些数字是怎么算出来的？」我没有实现** —— UIUX §8.1 终裁版明确写了该层已被裁掉、从未进入 Spec，理由是「在自己产品里开了一条绕过自己硬约束的后门」。
→ **这一条与任务书里画的示意图不一致，需你确认。** 若你确认要恢复这个入口，我再实现。

### ② 禁止出现「Token」

已加为 P0 门禁第 8 项，`report`/`trial`/`jobs` 三个老板面向目录零命中。
试跑页的错误码也做了业务语言映射（`TARGET_REQUIRES_JS_RENDER` → 「这个网址需要浏览器才能加载」），
**不把后端错误码直接抛给老板** —— 抛码等于告诉他这是开发工具。

### ③ 待确认队列用 `Hand` 不用 `TriangleAlert`

- `block-needs-action.tsx`：`Hand` + `text-[var(--info)]`，**未用 `--warn`/`--danger` 作容器色**
- `trial-result-view.tsx` 顶部提示条：同样用 `Hand`
- 三个通道（图标+颜色+文字）齐全，满足 CVD 硬约束

### ④ 信任指标 P0 句式

`block-stopped.tsx` 的判定逻辑：

```
N = 0        → 「今天没有员工打断你。」（+ CircleCheckBig）
有未处理      → 「…其中 M 次还在等你。」（不保留「每次你都做了决定」）
全部已处理    → 「…每次你都做了决定。它们没有一次是猜的。」
awaiting > 0 → 图标改用 muted，禁用 success 绿
```

**只声明系统能保证的事**：优先渲染后端 `message`（后端已按规则二选一生成），本地仅在 message 缺失时按同一规则兜底，
**计数一律取自后端字段，不自行编造**。

## 4. 任务 C：纯 BYOK 文案约束 —— 已固化为门禁

| 约束 | 落地方式 |
|---|---|
| 禁「充值/余额/平台额度」 | 门禁第 7 项，零命中 |
| 「API 预算」而非「额度」 | 沿用 `state-badge.tsx` 的 budget 态文案 |
| 「你的模型账单」 | 成本结论句主语固定为「生成这些产出，**你的模型账单**多了 X 元」 |
| 订阅费与 API 费不同区块 | API 费只出现在板块 ④；SaaS 订阅费前端**完全不渲染** |
| 预算预警用 `--warn` 不用 `--danger` | `STATE_MAP.budget` = `var(--warn)` |
| 预算动作不跳充值页 | 无充值路由，按钮 disabled |

## 5. 放行条件达成度

| # | 条件 | 前端 | 说明 |
|---|---|---|---|
| 1 | 认证 + RLS 隔离 | **前端完成** | 端到端需后端启动才能证明 RLS 生效 |
| 3 | F6-lite 五态机 UI | **完成** | 10 态全映射（`state-badge.tsx`），含 `stopping` 独立态 |
| 4 | 竞品监控端到端 | **完成** | 岗位库页 + 试跑页 |
| 5 | **汇报页显示产出含成本** | **完成** | 四板块 + 成本同页下钻 |

## 6. 需要裁决的 3 件事

### ① 成本下钻第 3 层：任务书 vs UIUX 冲突

- **任务书**画了 `[ 这些数字是怎么算出来的？ ]` 作为 token 级入口
- **UIUX §8.1 终裁版**写明该层「已被裁掉，从未进入 Spec」

我按 UIUX 实现（只到员工维度）。**若你确认以任务书为准，我需要先让设计师在 UIUX 落这一层**，不能前端自行加 —— 否则设计师要背一个她没签的字。

### ② CostBreakdown 缺环比与工时字段

`CostBreakdown` schema 只有 `agent_id`/`agent_name`/`task_count`/`cost_cents`/`total_cost_cents`。
UIUX §8.1 允许呈现「环比 ↑2.1%」与「约 4 小时人工」，但**无字段支撑**。
我的处理：**不渲染**，不编造「持平」。
→ 需确认：Phase 2 补不补这两个字段？补了我按 UIUX §8.1 实现（趋势必须带方向符号 + 数值）。

### ③ `/pending` 页不在 Phase 2 范围

待确认队列页未实现，导致两处 CTA 只能 disabled：
- `block-needs-action.tsx` 的「逐件处理」
- `pending-records.tsx` 的选项按钮

选择 disabled 而非链到不存在的路由 —— **一个点了跳 404 的入口，比一个明确说"还没开放"的按钮伤害更大**。

## 7. 设计契约冲突

无UIUX 违规。所有四板块空状态、密度、`Hand` 语义、信任指标句式均照 UIUX 实现，未自行改设计。

## 8. 失效模式自检

| # | 失效模式 | 结果 |
|---|---|---|
| 1 | Happy-path 偏差 | 加载/错误/空/全失败/待确认≥3 五态齐全，失败均给具体原因 + 重试 |
| 2 | 沉默逻辑错误 | 重点防守：`setSession` 加字段校验（防 `Bearer undefined`）；成本趋势/工时无字段则**不渲染**而非编造；日期按字符串解析防时区差一天 |
| 3 | 幻觉依赖 | 拦下 4 个不存在版本（eslint 9.42.0 等）；25 个图标名逐个核对真实导出；门禁第 6 项自动化 |
| 4 | 缺失系统上下文 | refresh rotation 并发去重（防重放吊销）；超时 15s；租户号只作展示不作关联键 |
| 5 | 性能盲区 | 单请求 15s 超时；组件卸载后不 setState；`tabular-nums` 避免布局抖动 |
| 6 | 静默缺失 | lint + tsc + build + 8 项门禁四道拦截 |

**已知未覆盖**：无单元测试与 E2E。Phase 2 骨架期未引入测试框架（会新增依赖，需锁版本）。
→ 建议 Phase 3 补：成本格式化（四舍五入）、信任指标句式分支、空状态渲染 —— 这三处是「测试绿了也可能悄悄算错」的高发区。