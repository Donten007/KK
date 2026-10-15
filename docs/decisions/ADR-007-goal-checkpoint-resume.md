# ADR-007: Goal 长任务采用 LangGraph Checkpointer（PostgreSQL）实现挂起与断点恢复

## Status
Accepted (2026-10-14)

## Background

**Goal 长任务是本产品的头号卖点，也是 EvoFlow 最难复刻的能力之一。**

场景定义：中小企业老板交一个任务给 Agent（"整理这个季度所有客户的应收账款，生成催款清单，逾期超30 天的单独列出来"），然后关掉电脑去开会。Agent 在云端继续跑，可能跑 2 小时、可能跨夜、可能中间需要等人类的审批。第二天老板打开页面，看到一份完整的报告和一个审批待办。

技术要求拆开看：

| 要求 | 含义 | 为什么难 |
|------|------|---------|
| **后台挂起** | 用户断开连接后任务继续跑 | 长任务不能挂在 HTTP 请求生命周期里（请求有超时、进程会被回收） |
| **断点恢复** | 进程崩溃/发版后从断点继续，不是从头重跑 | 从头重跑意味着重复调用 LLM，**直接等于重复烧钱**；一个跑 3 小时的任务重跑一次可能损失几十上百元 |
| **状态持久化** | 执行到哪一步、用了哪些工具、花了多少钱，全部可查 | 这是"可观测性"和"费用统计"两个功能模块的数据基础 |
| **断线不丢进度** | 用户手机断网 4G切 WiFi，进度不丢 | 流式传输必须支持续传 |
| **中间可等人** | 执行到某步暂停，等人类审批，批准后带上下文继续 | 这是"审批流"和"智能体员工组织树汇报"的基础能力 |

这五条加起来，指向同一个答案：**必须有持久化的执行引擎**，而不能是在请求里跑一个长async 函数。

## Decision

**采用 LangGraph 的 Checkpointer 机制实现挂起与断点恢复，checkpoint 持久化到 PostgreSQL。**

**锁定**：
- `langgraph==1.2.15`
- `langgraph-checkpoint-postgres==3.1.3`
- checkpoint 表存于独立 schema `langgraph_checkpoints`
- `thread_id` = `goal_id`（业务层生成，全局唯一）
- 使用 LangGraph 的 `interrupt()` / `Command(resume=...)` 实现 human-in-the-loop 挂起

**配套**：
- 事件总线：Redis Streams `goal:events:{tenant_id}:{goal_id}`（SSE 消费，详见 ADR-002）
- 定时巡检：worker 每 30 秒扫描 `checkpoint` 表，捞出"孤儿"run（worker 死了但 run 状态还是 running）并恢复

## Alternatives Considered

### 方案 A：LangGraph Checkpointer + PostgreSQL（选中）

**评分：5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 断点恢复正确性 | 高 | 5 | 每节点执行后落checkpoint；进程死亡后**重放事件历史并从最后 checkpoint 继续**，不是重启作业 |
| 挂起/恢复 | 高 | 5 | `interrupt()` + `Command(resume=...)` 是一等能力，审批流原生支持 |
| 成本控制 | 高 | 5 | 恢复时重放已完成的节点，但**不重复执行 LLM 调用**（已完成的节点从 checkpoint 读结果） |
| 与 Agent 图集成 | 高 | 5 | 与 ADR-001 同一套图，零额外抽象 |
| 状态膨胀 | 中 | 3 | checkpoint 表会快速增长，需保留策略 |
| 运维成本 | 高 | 5 | 无新增组件，与业务库同一套备份 |

**决定性能力**：Checkpointer 2.0 引入了**增量状态序列化**——只有状态差异（delta）被写入持久化存储。这让 72 小时级长流程的断点续作从"不可能"变成"可能"。有实测显示 200 并发 Agent 时，内存稳定在 8.5GB（对比内存态方案 47GB 失控）。

### 方案 B：Temporal（专用 durable execution 引擎）

**评分：3.5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 恢复正确性 | 高 | 5 | append-only 日志 + 重放，比 checkpoint 更严格（区分"已记录"和"已执行"的确定性更强） |
| 与 LangGraph 重叠 | 高 | 1 | **职责严重重叠**，两层状态机并行 |
| 学习曲线 | 中 | 2 | Workflow/Activity/Signal/Query/Update/Namespace 概念重 |
| 运维成本 | 高 | 2 | 需运营真实集群，Cloud从 $100/月起 |
| 成本 | 中 | 3 | $50/百万 Actions。但对比：20 万次运行/月的负载下最便宜的引擎是 0.06%、最贵 0.68% 的模型 token 费用——**引擎成本不是决策因素** |

否决理由：**职责重叠**。两者都想做持久化编排，同时引入会出现两层状态机、两套重放语义、两处失败点。Temporal 的优势在"跨服务的超长业务流程（数天/数月）"，我们的 Goal 虽然长但状态复杂度未到需要 Temporal 的程度。**保留为 Phase 2 升级路径**：若出现跨服务工作流需求（而非单 Agent 图内长任务），再评估。

### 方案 C：Celery / Dramatiq / arq（传统任务队列）

**评分：2 / 5**

**根本性缺陷：它们不解决"断点恢复到图内位置"这个问题。**

Celery 的重试是从头重跑整个 task。要在 task 内实现断点恢复，你得自己在 task 里维护状态机 + 存储每步状态——**这等于重新实现 LangGraph 的checkpointer，而且做得更差**（没有图语义、没有 interrupt、没有确定性重放）。

补充事实：**arq已进入维护模式**（maintenance only），不作为新项目选型。

| 方案 | 评分 | 结论 |
|------|------|------|
| Celery 5.x | 2.5 | 成熟但需自建状态机|
| Dramatiq 1.17+ | 2 | API 更干净，但不解决核心问题 |
| arq 0.26+ | 1.5 | 维护模式，排除 |
| FastAPI BackgroundTasks | 0 | 同进程同内存，进程死任务丢。明确错误答案 |

但**传统队列在另一个场景仍然需要**（见 ADR-008：驱动"何时启动一个图"）。两者职责分离，不冲突。

### 方案 D：Redis Streams 做 checkpoint

**评分：1.5 / 5**

Redis Streams 有消费者组、ACK 机制，看起来很像。但：checkpoint 状态可能很大（对话历史、文件内容），Redis 是内存存储不适合存大状态；Redis 的持久化（RDB/AOF）在断电场景下可能丢最后几条；且 checkpoint 需要的是"按 thread_id 查最新快照"的强查询语义，Redis 不擅长。

否决。**但 Redis Streams 用来做"事件流"（给 SSE 消费）非常合适**——这是它的正确用途，ADR 已如此设计。

## Consequences

### 正面

- **成本可控**：恢复时不重复调用 LLM，直接从 checkpoint 读已完成节点的结果
- **审批流原生支持**：`interrupt()` 暂停 + `Command(resume=...)` 恢复，携带人类修改继续（不只是 ALWAYS/NEVER 的简单中止）
- **状态全可查**：checkpoint 表 + 业务表联合支撑"可观测性"和"费用统计"两个功能模块
- **零新增组件**：checkpoint 在业务库同一实例

### 负面

**五条必须内嵌 Spec 的已知坑：**

1. **【最致命】节点内的业务写入必须幂等**。checkpoint 写入和业务数据写入**不在同一事务里**。崩溃时刻可能"业务写成功但 checkpoint 未落盘"→ 重放时该节点再执行一次 → **产生重复副作用**。硬约束：所有图节点内的 DB 写入必须带唯一幂等键（推荐 `thread_id + node_name + attempt_ordinal`，写入用 `INSERT ... ON CONFLICT DO NOTHING`）

2. **checkpoint 表会快速膨胀**。长任务每节点一个 checkpoint，每个 checkpoint 存全量状态。3 小时任务可能产生几十个 checkpoint，每个几 MB。必须设计保留策略：活跃 run 全量保留，终止 run 的 checkpoint 只留最近 N 个或 T 天后归档到对象存储

3. **孤儿 run 巡检不可省**。worker 被 OOMKill / 机器宕机后，run 状态停留在 `running` 但没有 worker 在跑。必须有独立的巡检器（每 30 秒扫 `checkpoint` 表中最后更新时间超阈值的 run）并恢复或标记失败。**这不是可选优化，这是可用性必需品**

4. **`thread_id` 必须等于 `goal_id`，不可用随机 UUID**。否则用户刷新页面找不到自己的任务。这个映射关系必须由业务层保证，不能让 LangGraph 自己生成

5. **LangGraph 会 await 所有 pending checkpoint 写入后才resolve `invoke()`/`stream()`**。这意味着 checkpoint 写入延迟会计入响应延迟，高频小节点场景下需要批量/异步 checkpoint 策略

**其他负面**：

- **checkpoint schema 会随LangGraph 版本变化**。锁定版本号，禁止自动升级；升级前必须跑 ADR-001 的端到端验证
- **LLM 调用本身不确定**。LangGraph 的确定性重放假设"节点执行是纯函数"，但 LLM 输出不确定。实际语义是"已完成节点的重放不重新调用 LLM"，所以节点的 LLM 调用必须放在节点内部而非图外

## Related ADRs

- ADR-001（Agent 内核）—— 本 ADR 是其"持久化执行"能力的具体落地
- ADR-002（FastAPI + SSE）—— SSE 从 Redis Streams 读事件，不直连worker
- ADR-008（长任务队列）—— 职责分离：队列管"何时启动图"，本 ADR 管"图内断点恢复"
- ADR-003（多租户 RLS）—— checkpoint 表也启用 tenant 过滤

## Verification

**存在性核验**：

```bash
pip install "langgraph==1.2.15" "langgraph-checkpoint-postgres==3.1.3"
python -c "from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; print('ok')"
```

**端到端验证步骤**：

1. **基础挂起与恢复**：
   - 定义 5 节点图，第 3 节点后 `interrupt()`
   - 运行到 interrupt，断言：run 状态 = `waiting_approval`
   - 执行 `Command(resume={"approved": True})`
   - 断言：图从第 4 节点继续，第 5 节点执行完成
2. **进程崩溃恢复（核心用例）**：
   - 运行到第 4 节点后 `SIGKILL` worker
   - 断言：数据库中 run 状态仍为 `running`（成为孤儿）
   - 启动巡检器，断言 30 秒内该 run 被重新拾起
   - 断言：图从**第 4 节点**继续，不是从第 1 节点重跑
3. **幂等性断言（阻断级）**：
   - 在第 3 节点内写入一条业务记录，幂等键 = `thread_id + node_name`
   - 崩溃发生在"业务写入成功、checkpoint 落盘前"
   - 恢复后断言：业务记录**只有 1 条**（`COUNT(*) = 1`）
   - 若为 2 条即幂等机制失效——这是会导致客户重复扣款/重复发邮件的严重 bug
4. **成本断言**：
   - 记录崩溃前后的 LLM 调用次数
   - 断言：恢复后**第 1-3 节点的 LLM 调用次数没有增加**
   - 实际费用断言：恢复产生的 token 消耗 < 原运行的 20%
5. **SSE 断线续传**：
   - 前端拿到前 20 条事件后断开网络
   - 30 秒后恢复
   - 断言：浏览器自动带 `Last-Event-ID`，服务端从该位置续发，最终事件序列**完整无缺口无重复**
6. **孤儿巡检**：
   - 人为 kill worker，不重启
   - 断言：run 在 5 分钟内被标记为 `failed` 或被新 worker 恢复，**不允许永久停留在 `running`**
7. **checkpoint 膨胀**：
   - 跑一个模拟 3 小时（加速 100倍）的任务
   - 断言：checkpoint 表增长量在预算内；终止后的保留策略生效（只留最近 N 个）

第 3 条为阻断级：幂等失效意味着重复副作用（重复扣款、重复发邮件、重复下单），是客户可见的严重事故。