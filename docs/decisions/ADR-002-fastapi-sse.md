# ADR-002: 后端框架采用 FastAPI + SSE 流式，不引入 WebSocket

## Status
Accepted (2026-10-14)

## Background

产品有 3 类需要流式/长连接的场景：

1. **对话流式输出** —— token 逐字返回给用户
2. **Goal 长任务进度回传** —— 用户提交一个跑 3 小时的任务，前端要实时看到进度（当前执行到哪个节点、调用了哪些工具、花了多少钱）
3. **智能体员工状态推送** —— 后台 Agent 自主开始/结束工作、发起审批请求

这三类场景的共同特征是**服务端 → 客户端单向推送**。用户侧的输入（发消息、取消任务）走独立的普通 HTTP 接口即可，不需要在同一条连接上双向通信。

同时后端要承载：多租户 RLS 会话管理、异步任务编排、PostgreSQL async 驱动、SSE 长连接在 Nginx/Cloudflare 后的存活。

## Decision

**后端框架**：FastAPI `0.143.1`（Python `3.13.16`），ASGI 服务器 Uvicorn `0.54.0`
**流式传输**：SSE（`text/event-stream`），不引入 WebSocket
**数据校验**：Pydantic `2.14.1`（Rust 内核，v2 原生）
**ORM**：SQLAlchemy `2.1.4` async + asyncpg `0.32.0`
**迁移**：Alembic `1.20.0`

SSE 端点统一挂在 `/api/v1/.../stream` 路径下，全部返回 `Content-Type: text/event-stream`。

## Alternatives Considered

### 方案 A：FastAPI + SSE（选中）

**评分：4.5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 与 LangGraph 契合 | 高 | 5 | 同为 Python 生态，LangGraph 的 `astream` 直接是 async generator，接进 `StreamingResponse` 零胶水 |
| 单向流式适配 | 高 | 5 | SSE 天生就是服务端单向推送，EventSource 自带自动重连 |
| 断点续传 | 高 | 5 | 规范内置 `Last-Event-ID`，浏览器重连时自动带上，服务端据此续发——这是 Goal 长任务断线不丢进度的关键 |
| 基础设施兼容 | 高 | 5 | 普通 HTTP，走标准 HTTP 头（`Authorization: Bearer`），Nginx/Cloudflare/企业代理基本不挡 |
| 双向通信 | 中 | 2 | 不支持，客户端无法在流中推送数据 |
| HTTP/1.1 连接数限制 | 中 | 2 | 浏览器对同源有 6 条并发连接硬上限（Chrome/Firefox 标记为 Won't Fix） |

HTTP/1.1 的 6 连接限制是真实约束。缓解方案：前端**单条聚合 SSE 连接**（所有任务的进度事件复用一条流，按 `thread_id` 在服务端做多路复用），而不是每个任务开一条。这与架构文档 §6.4 的事件总线设计一致。同时全站强制 HTTP/2（HTTP/2 下 SSE 走多路复用，默认 100 条并发流，6 连接上限消失）。

### 方案 B：FastAPI + WebSocket

**评分：3 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 双向通信 | 中 | 5 | 唯一优势项，但我们的场景不需要 |
| 断线重连 | 高 | 2 | 无内建重连。close 事件后连接就是关的，退避/重连/状态恢复全部要自己写，且各家实现质量参差 |
| 流中断恢复 | 高 | 1 | 无 `Last-Event-ID` 等价机制。30秒响应被腰斩，要么从头重发 prompt，要么自建续传协议 |
| 代理/防火墙兼容 | 高 | 2 | 老 nginx 未配 Upgrade 头会直接掐握手；企业 DPI 防火墙（Sophos/WatchGuard/McAfee）可能丢帧或改帧 |
| 背压 | 中 | 2 | 无内建背压。消息来得比处理快则内存暴涨，需要自己实现丢弃/合并策略 |
| 实现复杂度 | 中 | 3 | 要自己写帧解析、心跳、重连、状态恢复 |

否决理由：核心否决项是**流中断恢复**。Goal 长任务跑 3 小时，用户的手机会在 4G/5G/WiFi 之间切换，连接必然断。SSE 的 `Last-Event-ID` 是规范级的、由所有浏览器一致实现的；WebSocket 的重连质量完全取决于我们自己写的代码。这个差异在长任务场景下是决定性的。

另有工程教训：实际项目中常见"因为双向听起来更高级所以上 WebSocket"，结果测试环境 nginx 没配 Upgrade 头，连接刚握手就被掐，前端疯狂重连。SSE 走普通 HTTP，根本不存在这类问题。

### 方案 C：NestJS / Express（Node.js）

**评分：2.5 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 与 LangGraph 契合 | 高 | 1 —— LangGraph 主力是 Python。JS 版（`@langchain/langgraph`）存在但生态深度、checkpointer 成熟度、文档都落后一截 |
| AI 生态 | 高 | 2 |
| 前端同构 | 低 | 4 —— TypeScript 前后端同语言是真实优势 |
| 长任务流式 | 高 | 4 |

否决理由：选型的第一约束是"Agent 内核用 Python"，如果后端用 Node，等于在最核心的子系统上跨语言，checkpoint 读写、双端调试、团队技能全部分裂。TypeScript 同构的好处远不及这个代价。

### 方案 D：gRPC + 独立网关

**评分：2 / 5**

浏览器无法直接用 gRPC，需要 gRPC-Web 代理层，MVP 阶段这是纯负担。SSE 的 HTTP 语义在浏览器端零成本可用。

## Consequences

### 正面

- **Agent 栈单语言**：LangGraph、FastAPI、SQLAlchemy 全在 Python，checkpoint 表读写、异步流、类型注解只有一套心智模型
- **SSE 的 `Last-Event-ID` 直接支撑 Goal 长任务的断线续传**：前端不写任何重连逻辑，浏览器自动带 `Last-Event-ID`，服务端从 Redis Streams 的对应位置续发
- **标准 HTTP 头传认证**：`Authorization: Bearer <jwt>` 直接生效，不需要把 token 塞 query string（那是 SSE 的常见安全陷阱）
- **FastAPI 自动产出 OpenAPI 3.1 规范**：与团队要求的 `openapi.yaml` 契约天然对齐，前端据此生成 TS 类型

### 负面

**必须处理的四个 SSE 陷阱（缺一个就线上流式直接坏掉）：**

1. **Nginx 缓冲**：默认会缓冲响应体直到连接关闭，流式效果完全消失。必须设置 `X-Accel-Buffering: no` + `proxy_buffering off`
2. **Cloudflare 100 秒空闲超时**（免费版）：Agent 调工具时可能 90 秒不产生 token，连接会被 Cloudflare 静默掐断。必须每 30 秒发一次 SSE 注释行心跳（`: keepalive\n\n`）
3. **ALB 60 秒空闲超时**：目标组需调至 300 秒
4. **HTTP/1.1 的 6 连接限制**：必须用单条聚合 SSE 连接 + 服务端多路复用，不能每个任务开一条

其他负面：

- 纯 CPU 密集型任务（不走沙箱的那些，比如大规模 embedding 计算）会阻塞事件循环。必须全部推到沙箱或独立 worker 进程，API 进程只做 I/O 编排
- Uvicorn 单进程并发有限，需多 worker + 无状态部署（Session 状态必须在 Redis/PG，不能在进程内存里）

## Related ADRs

- ADR-001（Agent 内核）—— LangGraph 的 `astream` 是 SSE 数据源
- ADR-008（长任务队列）—— SSE 读的是 Redis Streams 事件流，不是直接读 worker

## Verification

**存在性核验**：

```bash
pip install "fastapi[standard]==0.143.1" "pydantic==2.14.1" \
            "sqlalchemy[asyncio]==2.1.4" "asyncpg==0.32.0" \
            "uvicorn[standard]==0.54.0" "alembic==1.20.0"
python -c "import fastapi, sqlalchemy, asyncpg; print('ok')"
```

**端到端验证步骤**：

1. 前端 `fetch()` 打开 `/api/v1/goals/{goal_id}/stream`，带 `Last-Event-ID: 42`
2. 断言：服务端**只推送 seq > 42 的事件**，不重发 42 之前的内容
3. 在工具执行阶段静默 90 秒（不发任何事件）
4. 断言：30 秒时收到 `: keepalive` 心跳行；整条连接未断开
5. 经过 Nginx（开启 `proxy_buffering off`）与 Cloudflare 各测一次，断言事件是**逐条到达**而非结束时一次性到达
6. 断开网络 10 秒后恢复，断言：浏览器自动重连且带上 `Last-Event-ID`，前端最终收到完整事件序列无缺口
7. 断言：`curl -N` 输出的首字节时间 < 2s（验证未发生缓冲）