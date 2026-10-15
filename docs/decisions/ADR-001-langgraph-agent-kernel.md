# ADR-001: Agent 内核框架采用 LangGraph

## Status
Accepted (2026-10-14)

## Background

产品需要复刻 EvoFlow 的 26 个功能模块，其中 4 个模块直接依赖 Agent 内核能力：

1. **Goal 长任务** —— 任务可挂起数小时乃至数天，进程重启后必须从断点恢复，不能从头重跑（从头重跑意味着重复付费调用 LLM）
2. **子Agent 委派** —— Lead Agent 动态派生子 Agent，需要并发控制、超时控制、进度回传
3. **Plan 模式** —— 需要图状的执行流，而非线性的 prompt 循环
4. **审批流（human-in-the-loop）** —— 智能体员工执行高风险动作前必须暂停等人类批准

这四项的共同技术要求是：**有状态的、可持久化的、可中断可恢复的执行图**。传统 `while True: llm.invoke(...)` 的 prompt 循环在架构上无法满足：进程一死状态全丢，且没有任何地方能记录"这一步执行过没有"。

EvoFlow 用了 LangGraph 内核。我们是干净室重写，不复用其源码，但"用有状态图编排 Agent"这个架构判断本身是被验证过的，不构成抄袭。

## Decision

采用 **LangGraph（Python，MIT 许可）** 作为 Agent 内核，锁定 `langgraph==1.2.15` + `langgraph-checkpoint-postgres==3.1.3`。

图执行的状态持久化落到我们自己的 PostgreSQL（与主库同实例、独立 schema `langgraph_checkpoints`）。

## Alternatives Considered

### 方案 A：自研状态机（自建图执行引擎）

**评分：2.5 / 5**

| 维度 | 权重 | 自研 | 说明 |
|------|------|------|------|
| 开发成本 | 高 | 极差 | 图执行 + checkpoint + 断点重放 + interrupt/resume 全部要自己写且自己测对，估算 3-4 人月，且大部分时间花在调试"重放语义正确性"上 |
| 可靠性 | 高 | 极差 | 重放语义的 corner case（副作用已执行但 checkpoint 未落盘）需要极精确的顺序保证，自研几乎必然踩坑 |
| 生态契合 | 高 | 差 | LangChain 生态 9000 万月下载，模型适配器、工具集、结构化输出都是现成的 |
| 灵活性 | 低 | 最优 | 自研上限最高 |
| 团队熟悉度 | 高 | 差 | LangGraph 有大规模生产验证（Uber / LinkedIn / Klarna / Replit） |

否决理由：MVP 阶段"开发成本"和"可靠性"权重最高，自研在这两项上都是最差解。自研图引擎是"有空再优化"，不是 MVP 该做的事。

### 方案 B：CrewAI（角色化多 Agent 协作）

**评分：3 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 上手速度 | 高 | 5 —— 抽象最小，idea-to-production < 1 周 |
| 控制力 | 高 | 2 —— 复杂分支逻辑与角色抽象对抗，出了问题没有精细的抓手 |
| 持久化执行 | 高 | 1 —— 无 checkpoint/resume |
| Human-in-the-loop | 中 | 2 —— 只有 ALWAYS/NEVER/TERMINATE 模式，不支持"暂停等审批后带修改继续" |
| 长期运行 | 高 | 1 —— 假设 Agent 生命周期等于单次会话，内存态协作 |

否决理由：核心否决项是**没有持久化执行**。Goal 长任务是本产品的头号卖点，做不到断点恢复就不能上。另有生产报告指出 CrewAI 在 200 并发下内存占用失控（长流程场景上下文全驻留内存），与我们 Goal 长任务的形态直接冲突。

### 方案 C：Temporal（durable execution 引擎）

**评分：2.5 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 持久化执行 | 高 | 5 —— 业界最强，append-only 日志 + 重放 |
| 与 LLM 图编排契合 | 高 | 2 —— Temporal 是通用工作流引擎，不理解"图节点/LLM 调用/工具调用"，要自己写一层适配 |
| 运维复杂度 | 高 | 2 —— 需要运营一个真实集群（Temporal Cloud 从 $100/月起，团队维护成本更高） |
| 学习曲线 | 中 | 2 —— 概念重（Workflow/Activity/Signal/Query/Update/Namespace） |
| MVP 适配度 | 高 | 2 —— 引入 Temporal 后我们大部分代码变成"把 LangGraph 塞进 Activity"，两层抽象互相打架 |

否决理由：Temporal 与 LangGraph **职责重叠**。两者都想做"持久化编排"，同时引入会出现两层状态机、两套重放语义、两处失败点。对于 MVP 这是纯粹的复杂度浪费。Temporal 的价值在"跨服务的超长业务流程（数天/数月）"，我们的 Goal 长任务虽然长，但状态复杂度远没到需要 Temporal 的程度。

### 方案 D：Microsoft Agent Framework / Pydantic AI V2 / LlamaIndex Workflows

**评分：2 / 5**

- Microsoft Agent Framework 1.0（2026-04-03）：.NET 生态为主，Python 支持是次要的；我们是 Python 栈
- Pydantic AI V2（2026-06-23稳定）：类型安全优秀，但无内置持久化执行，需要自己接
- LlamaIndex Workflows 1.0：重心在"对索引数据做推理"，与我们的核心场景（Agent 编排）不匹配

否决理由：均缺少开箱即用的持久化执行，或生态与我们的主栈错位。

## Consequences

### 正面

- **Goal 长任务的断点恢复有了确定性答案**：LangGraph 的 Checkpointer 在每个节点执行后落盘，进程死亡后从最后 checkpoint 重放事件历史并继续，而不是重启整个作业
- **Checkpoint 2.0 的增量状态序列化**：只有状态差异（delta）写入持久化存储，这让 72 小时级长流程的断点续作成为可能——是"精确重放计算状态"，不是"恢复对话"
- **MCP 工具是一等图节点**：MCP 工具的持久化、human-in-the-loop 中断、审计全部复用图的机制，不需要为工具单独造一套生命周期
- **MIT 许可**，无锁定成本，可自托管
- **checkpoint 落在我们自己的 PostgreSQL**，与业务数据同一套备份/灾备/事务体系，不引入第二套存储

### 负面

- **学习曲线陡**：需要团队建立"图 = 状态机"的心智模型，不能用 prompt 循环的直觉来写
- **样板代码多**：同样的图用 LangChain 高层 API 写要少很多代码
- **checkpoint 表会快速膨胀**：长时间运行的任务如果不清理 checkpoint 会吃掉大量存储。必须设计 checkpoint 保留策略（见架构文档 §7.3）
- **双写一致性风险**：业务数据写 PostgreSQL、checkpoint 也写 PostgreSQL，但不在同一事务里。节点内的业务写入必须**幂等**，否则重放会产生重复副作用。这是本项目最容易踩的坑，已在架构文档中列为 P0 约束

## Related ADRs

- ADR-002（后端框架与流式方案）—— LangGraph 的 streaming 能力需要 SSE 承载
- ADR-003（多租户隔离）—— checkpoint 表也必须在租户隔离范围内
- ADR-004（沙箱隔离）—— 图节点中的代码执行必须走沙箱
- ADR-008（长任务队列）—— LangGraph 管"图内断点恢复"，Hatchet/队列管"何时启动这个图"，两者职责分离

## Verification

**存在性核验**（依赖必须真实存在且版本可解析）：

```bash
pip install "langgraph==1.2.15" "langgraph-checkpoint-postgres==3.1.3"
python -c "import langgraph; print(langgraph.__version__)"
```

**端到端验证步骤**：

1. 起一个 5 节点的图，第 3 节点内写入一条业务记录（幂等键 `task_id + node_name`）
2. 让图运行到第 4 节点后 `SIGKILL` worker 进程
3. 重启 worker，用同一 `thread_id` 恢复
4. 断言：
   - 图从第 4 节点继续，不是从第 1 节点重跑
   - 第 3 节点的业务记录**只有 1 条**（幂等键生效，未重复写入）
   - checkpoint 表中该 thread 的记录数随节点推进单调递增
5. 上述任一断言失败即视为 ADR-001 的 Decision 不成立，需回退重评