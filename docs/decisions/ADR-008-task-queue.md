# ADR-008: 任务编排采用 arq 替代方案 Hatchet + Redis Streams 事件总线

## Status
Accepted (2026-10-14)

## Background

ADR-007 解决了"图内断点恢复"，但还有一个正交的问题：**谁来驱动这些图的执行？**

具体需求：

1. **调度触发**：智能体员工要"上班"——每天早上 9 点自动开始工作。需要 cron 能力
2. **任务分发**：一个 goal 被创建后，需要一个 worker 进程去跑它（HTTP 请求进程不跑长任务）
3. **并发控制**：同一租户同时最多 N 个 goal 在跑（防止一个客户刷爆共享资源）；单个 goal 最多 M 个子 Agent
4. **优先级队列**：付费租户的任务优先于免费租户
5. **失败重试 + 死信**：可重试的失败自动重试，不可重试的进死信队列人工介入
6. **事件广播**：worker 执行过程中产生的事件（token、工具调用、子 Agent 进度）要实时推给前端 SSE

**职责边界必须清晰**：

```
队列/Hatchet  → 何时启动、谁来跑、重试几次        （驱动层）
LangGraph     → 跑到哪一步、怎么恢复              （执行层）
Redis Streams → 发生了什么、推给谁看              （观测层）
```

三者不重叠。上一版ADR 曾考虑用 Celery，但发现 Celery 重试是从头重跑整个 task，无法恢复图内位置，故执行层归LangGraph。Celery 仍可用于驱动层，但有更贴合的选择。

## Decision

**采用 Hatchet（MIT 许可，PostgreSQL 支撑的分布式任务队列 + DAG 引擎）作为调度与任务分发层，Redis Streams 作为事件总线。**

**锁定**：
- Hatchet（自托管，MIT，无 SSPL 条款）
- PostgreSQL（与业务库同实例，独立 schema `hatchet`）
- Redis `8.1.0`（事件总线 + 缓存 + 限流）

**MVP 简化**：若 Hatchet 自托管部署遇到阻碍，降级路径为 `Redis Streams + 自研轻量 scheduler`（约 400 行代码，见 Consequences）。

## Alternatives Considered

### 方案 A：Hatchet 自托管（选中）

**评分：4 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 依赖数量 | 高 | 5 | **只需 PostgreSQL**——我们已经在跑了，零新增基础设施 |
| 许可 | 高 | 5 | MIT，无 SSPL / AGPL 传染，商业闭源安全 |
| 自托管成本 | 高 | 5 | 小规模 Postgres + 2-4 worker 容器约 $30-80/月 |
| Cron/定时 | 高 | 5 | 原生支持 cron 表达式，满足"智能体员工上班" |
| DAG/并发控制 | 高 | 4 | 支持任务编排、并发限制、优先级 |
| 成熟度 | 中 | 2 | v0.x（2026-09 为 v0.107.0），GitHub 7,949 stars，比 Temporal 年轻、生产案例少 |
| Python SDK | 中 | 3 | Go/Python/TS 均支持，非 Python-first |

**为什么选它**：三个决定性因素——

1. **零新增基础设施**。只依赖 PostgreSQL，我们已有。Celery 要 Redis（已有）+ 复杂配置；Temporal 要一整个集群；Inngest 要 Postgres + 自己的服务进程
2. **MIT 许可无传染**。对比 Inngest（SSPL，2026-01 起转 Apache 但有 3 年转换期，期间有源码披露义务）和 Daytona（AGPL-3.0），Hatchet 是唯一干净的
3. **成本交叉点友好**。托管 Hatchet Cloud 入门已涨到 $500/月（2026-07 重新定价，旧的 $25 Starter 已下线），但**自托管不受影响**，$30-80/月

### 方案 B：Celery

**评分：3 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 成熟度 | 高 | 5 | 18,000+ stars，生产验证最充分 |
| 功能完备 | 高 | 5 | chains/groups/chords/路由/优先级/Flower 监控，全套 |
| 依赖 | 高 | 3 | Redis + Beat 独立进程 + Flower |
| 配置复杂度 | 高 | 2 | **配置面大到能吃掉一周**，且Python async 支持尴尬（需 eventlet/gevent） |
| 与 FastAPI async契合 | 中 | 2 | async 任务需绕道 |

否决理由：**功能过剩 + async 尴尬**。我们不需要 chains/groups/chords（那是工作流编排，而编排已由 LangGraph 承担）；FastAPI 是 async-first，Celery 的 async 故事需要 eventlet/gevent workaround。且 Beat 独立进程是额外的运维点（且只能跑一个，多跑会重复调度）。

### 方案 C：Temporal

**评分：2.5 / 5**

功能最强（append-only 日志重放、成熟的生产验证、SOC 2/HIPAA）。但：

- **运维成本最高**：需运营真实集群，Cloud 从 $100/月起
- **概念负担**：Workflow/Activity/Signal/Query/Update/Namespace
- **职责重叠**：与 LangGraph 的持久化执行重叠（同 ADR-007 的否决理由）
- **成本**：$50/百万 Actions。虽只占模型费用的 0.06-0.68%，但那是"占比小"不是"成本低"

保留为 Phase 2：若出现跨服务的超长业务流程需求，升级到 Temporal。

### 方案 D：Inngest

**评分：2.5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 依赖 | 高 | 3 |自托管也是 Postgres + 服务进程 |
| 许可 | 高 | 2 | **SSPL，至2026-01 起 3 年后转 Apache 2.0**——期间有源码披露义务，商业产品需法务确认 |
| TypeScript | 中 | 5 | TS-first（我们是 Python 栈，优势打折） |
| 定价 | 中 | 3 | Hobby 免费 5万 executions/月，Pro 从 $99/月起|

否决理由：**许可风险**。SSPL 的源码披露义务与"商业闭源 SaaS"存在潜在冲突，需要法务评估才能推进。对于 MVP 阶段，不该引入需要法务决策的依赖。

### 方案 E：Trigger.dev

**评分：2.5 / 5**

TS-first，Apache 2.0 干净，有 AI Agent 专用 SDK（2026-09-14 发布 `chat.agent` / `streamText`）。但我们是 Python 栈，TS SDK 的优势用不上；计费按 compute-second，对我们 60秒模型延迟的负载不利（$410.60/月 vs Hatchet $90.00/月，同一 20 万次运行负载）。

### 方案 F：Dramatiq / RQ / FastAPI BackgroundTasks

**评分：2 / 5**

- Dramatiq 1.17+：API 干净、有内置死信，但没有 DAG/cron/并发控制的高级形态
- RQ：极简，Redis only，但无 async 支持、无内置重试策略
- FastAPI BackgroundTasks：**明确排除**——同进程同内存，进程死任务丢。这是"错误答案"而非"权衡"

## Consequences

### 正面

- **零新增基础设施**：只依赖已有 PostgreSQL
- **许可干净**：MIT，商业闭源无风险
- **自托管成本可控**：$30-80/月（小程序额）
- **原生 cron**：直接满足"智能体员工上班"调度
- **版本可控**：v0.x 意味着 API 可能变，锁定版本 + 适配层隔离

### 负面

**必须内嵌 Spec 的五条约束：**

1. **【最高风险】Hatchet 仍是 v0.x**（2026-09 为 v0.107.0）。API 破坏性变更风险真实存在。**必须写适配层**（`app/services/scheduler/` 下约 100 行），业务代码只调我们的 `Scheduler.enqueue()` / `Scheduler.register_cron()`，不直接 import Hatchet SDK。这样换掉/升级时只改一个文件

2. **必须实现幂等**。Hatchet 是 at-least-once 投递，任务**必然会重跑**。所有任务函数必须幂等。传 ID 不传对象（传对象是序列化陷阱+ 数据陈旧）

3. **重试必须有上限**。默认重试次数需显式设定（建议 3次指数退避）。无限重试在故障时放大灾情

4. **Beat/调度器只跑一个**。多实例会导致重复调度。需要分布式锁（PG advisory lock）保证单点

5. **MVP 降级路径必须提前验证**：如果 Hatchet 自托管在阶段 3 仍不稳定，降级到 `Redis Streams + 自研scheduler`（约 400 行：消费者组 + PG advisory lock + cron 表 + 死信表）。**降级方案要在阶段 2 就跑通 POC，不要等到需要时才发现**

### 中性：并发控制的分层设计

| 层级 | 控制项 | 默认值 | 说明 |
|------|-------|-------|------|
| 租户级 | 同时运行的 goal 数 | 5（可按套餐调整） | 防单客户刷爆共享资源 |
| goal 级 | 子 Agent 并发数 | 5 | 防单任务内爆 |
| 全局级 | 同时运行的 goal 数 | 200 | 防总量过载 |
| 沙箱级 | 每沙箱 CPU/内存/PID | 见 ADR-004 | 防资源耗尽 |

这四层缺一不可。只有全局限制会被单租户打爆，只有租户限制会被多租户总和打爆。

## Related ADRs

- ADR-007（Goal 断点恢复）—— 职责分离：本 ADR 管驱动，ADR-007 管图内恢复
- ADR-002（FastAPI + SSE）—— SSE 消费的是 Redis Streams，不是直接连 worker
- ADR-004（沙箱）—— worker 进程中的工具执行走沙箱
- ADR-009（可观测性）—— 任务事件是成本归集的原始数据

## Verification

**存在性核验**：

```bash
docker run -d --name hatchet-db -e POSTGRES_PASSWORD=hatchet postgres:18-alpine
pip install hatchet-sdk   # 锁定版本号
```

**端到端验证步骤**：

1. **基本分发**：enqueue 一个 goal，断言：worker 在 5 秒内拾取，run 状态流转正确
2. **幂等性断言（阻断级）**：同一 job_id 投递 3 次，断言：副作用只发生 1 次（用业务表的 `COUNT(*)` 验证）
3. **崩溃恢复**：worker 执行中 `SIGKILL`，断言：任务被重新拾取（结合 ADR-007 的孤儿巡检）
4. **重试上限**：让任务必然失败，断言：重试 3 次后进死信队列，**不无限重试**
5. **cron 调度**：注册一个每分钟任务，断言：连续 3 个周期都触发，无漏无重
6. **单点调度断言**：启动 2 个 scheduler 实例，断言：**总触发次数与 1 个实例时相同**（PG advisory lock 生效）
7. **并发限制**：配置租户级上限为 5，向该租户提交 10 个 goal，断言：**同时 running 不超过 5**
8. **事件流**：任务执行中断言：Redis Stream `goal:events:{tenant}:{goal}` 中有事件，顺序单调递增 seq；断言：SSE 端点能读到全部事件
9. **降级路径POC**：用 Redis Streams + 消费者组实现最小 scheduler，断言：能完成 enqueue/消费/cron/死信四个功能，为 Hatchet 不可用时留退路

第 2、6、7 条为阻断级。