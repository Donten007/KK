# OPCAgentAI 架构设计文档

> 项目：复刻 EvoFlow 全部功能的多租户 SaaS 商业产品
> 目标客户：中小企业老板
> 架构师：高见远（首席架构师）
> 版本：v1.0（Phase 1 调研产出）
> 日期：2026-10-14

---

## 0. 阅读指引

本文档是 Phase 2（技术 Spec）的上游依据。关键决策的详细论证见 `docs/decisions/` 下的 ADR。

| ADR | 决策 |
|-----|------|
| [ADR-001](decisions/ADR-001-langgraph-agent-kernel.md) | Agent 内核框架 |
| [ADR-002](decisions/ADR-002-fastapi-sse.md) | 后端框架与流式方案 |
| [ADR-003](decisions/ADR-003-multi-tenant-rls.md) | 多租户隔离方案 |
| [ADR-004](decisions/ADR-004-sandbox-isolation.md) | 沙箱隔离方案 |
| [ADR-005](decisions/ADR-005-pgvector.md) | 向量数据库 |
| [ADR-006](decisions/ADR-006-frontend-stack.md) | 前端框架与图标库 |
| [ADR-007](decisions/ADR-007-goal-checkpoint-resume.md) | Goal 长任务断点恢复 |
| [ADR-008](decisions/ADR-008-task-queue.md) | 任务编排与事件总线 |
| [ADR-009](decisions/ADR-009-agent-staff-scheduling.md) | 智能体员工调度 |
| [ADR-010](decisions/ADR-010-governance-layer.md) | 治理层自建 |
| [ADR-011](decisions/ADR-011-long-task-engine.md) | F6 长任务引擎与无进展检测 |
| [ADR-012](decisions/ADR-012-budget-reservation.md) | 预算预占防超卖 |
| [ADR-013](decisions/ADR-013-model-capability.md) | 模型能力标签与前置校验 |
| [ADR-014](decisions/ADR-014-web-access-tiers.md) | 网页访问能力分三级（MVP 只做 L1） |
| [ADR-015](decisions/ADR-015-metric-definitions.md) | Go/No-Go 判据指标口径与可计算性 |
| [ADR-016](decisions/ADR-016-icon-gate-and-s1-fix.md) | 图标可导入性门禁 + S1 检测缺陷修正 |
| [ADR-017](decisions/ADR-017-abort-state-and-visibility.md) | 中止态建模 + 事件可见性分级 + 用量接口分离 |
| [ADR-018](decisions/ADR-018-circuit-break-semantics.md) | 熔断语义分离 + 图标删除门禁 + F8 取舍排序 |
| [ADR-019](decisions/ADR-019-pure-byok-cost-visibility.md) | 纯 BYOK 下的成本预估与账套号 |

**本次不做（out-of-scope）**：本文档不含UI 设计规范、不含 API 端点清单（属Phase 2 openapi.yaml）、不含具体表 DDL（属 Phase 2）。本文档只锁定**架构与版本**。

---

## 1. 架构总览

### 1.1 分层架构图

```
+-----------------------------------------------------------------------+
|  表现层  Next.js 16.4 (App Router) + React 19.3 + Tailwind 4.3        |
|  lucide-react 1.57.0 锁为唯一图标库                                   |
|  - 营销页 (SSR/SEO)                - 工作台 (登录墙后)                |
|  - SSE 客户端 (单条聚合连接)        - 移动端响应式                     |
+---------------------------+-------------------------------------------+
                            | HTTPS / SSE
+---------------------------v-------------------------------------------+
|  网关层  Nginx (proxy_buffering off) / Cloudflare                     |
|  - TLS 终止  - SSE 心跳透传  - 静态资源缓存                           |
+---------------------------+-------------------------------------------+
                            |
+---------------------------v-------------------------------------------+
|  API 层  FastAPI 0.143.1 + Uvicorn 0.54.0 (多 worker, 无状态)       |
|  - 路由(api/)  - 依赖注入(api/deps.py)  - 中间件(middlewares/)         |
|  - 统一响应 {code, data, message}  - 限流  - RBAC                |
+---+------------------+--------------------+----------------------+------+
    |                  |                    |                      |
+---v------------+  +-v--------------+  +---v-----------------+  +--v------------------+
| Agent Worker   |  | Scheduler    |  |  Sandbox Supervisor|  | Governance Worker   |
| Hatchet worker |  | Hatchet cron |  |  gVisor runsc      |  | 费用聚合/孤儿巡检    |
| LangGraph 图执行|  | + 单点锁      |  | Docker + 加固      |  | 审计/配额熔断        |
| Checkpointer   |  +--------------+  +---+-----------------+  +--+------------------+
| (PG schema)    |                    |                      |
+---+------------+                    v                      v
    |                    +------------+----------+  +------+------------------+
    |                    | Firecracker 节点集群   |  | Redis 8.1.0             |
    |                    | (Phase 2, 预留)       |  | Streams(事件总线)       |
    |                    | 沙箱池 (MVP: runsc)   |  | 缓存/限流/租户上下文     |
    |                    +-----------------------+  +-------------------------+
    |
+---v--------------------------------------------------------------------+
|  数据层  PostgreSQL 18.x + pgvector 0.8.7                |
|  - public: 业务数据 (26 个模块)          ENABLE+FORCE RLS|
|  - langgraph_checkpoints: Agent 检查点 RLS               |
|  - hatchet: 调度器内部状态                                |
|  - audit: 审计日志 (append-only)                          |
+---+-------------------------------------------------------------+
    |
+---v-------------------+          +------------------------------+
| 对象存储 (S3 兼容)     |          | 外部服务                     |
| - 知识库原文档          |          | - LLM (BYOK 优先)          |
| - 沙箱产物              |          | - MCP Servers               |
| - checkpoint 归档|          | - IM (企微/钉钉/飞书)        |
+------------------------+          +------------------------------+
```

### 1.2 与 EvoFlow 的本质差异

| 维度 | EvoFlow（源项目） | 本项目 |
|------|-------------------|--------|
| 形态 | Tauri 桌面单机 | Web 多租户 SaaS |
| 数据库 | SQLite 单文件 | PostgreSQL 18 + pgvector（RLS 强隔离） |
| 沙箱 | 本地沙箱（自认安全性最低，可访问宿主文件系统） | gVisor runsc + 加固容器 + 网络 default-deny |
| 多租户 | 不存在 | 三层防护（连接层 RLS / 查询层 tenant_id / 校验层越权测试） |
| 治理层 | 残缺（桌面应用天然限制） | 从零自建 5 模块（SSO/费用/可观测性/安全/任务中心） |
| 长任务 | 进程内执行，进程挂即挂 | LangGraph Checkpointer，崩溃后断点恢复 |
| Agent 内核 | LangGraph | LangGraph（干净室重写，仅借鉴架构思想） |
| 图标| 未约束 | lucide-react 1.57.0 锁定，禁止 emoji |

**干净室合规声明**：本项目不复用 EvoFlow 任何源码。仅借鉴"用有状态图编排 Agent"这一已被验证的架构判断。全部代码 100% 原创。

---

## 2. 技术栈锁定表

> 所有版本号均为 2026-10-14 从官方registry 实测拉取，非记忆推断。
> **锁版本规则**：`package.json` / `requirements.txt` 中使用精确版本号（无 `^`/`~`）。依赖升级必须走 ADR 修订流程 + 端到端验证。

### 2.1 前端

| 组件 | 锁定版本 | 说明 |
|------|---------|------|
| Next.js | `16.4.0` | App Router，Turbopack 默认 |
| React | `19.3.0` | 含稳定 View Transitions / Fragment Refs |
| TypeScript | `5.9.x`（5系最新稳定） | **不锁7.0.2**：TS 7为原生重写，生态兼容未充分验证 |
| Tailwind CSS | `4.3.3` | |
| **lucide-react** | **`1.57.0`** | **唯一图标库，P0 规则，见 §8** |
| Zod | `4.6.7` | 前后端共用校验（以openapi.yaml 生成类型为准） |

### 2.2 后端

| 组件 | 锁定版本 | 说明 |
|------|---------|------|
| Python | `3.13.16` | 稳定 GIL 模式；不用实验性free-threading |
| FastAPI | `0.143.1` | OpenAPI 3.1 自动产出 |
| Uvicorn | `0.54.0` | 多 worker |
| Pydantic | `2.14.1` | v2 Rust 内核 |
| SQLAlchemy | `2.1.4` | async + `async_sessionmaker` |
| asyncpg | `0.32.0` | 比 psycopg3 快约 5 倍 |
| Alembic | `1.20.0` | 迁移 |
| redis-py | `8.1.0` | Streams / 缓存 / 限流 |
| **langgraph** | **`1.2.15`** | Agent 内核 |
| **langgraph-checkpoint-postgres** | **`3.1.3`** | 断点恢复 |
| PyJWT | `2.10.x` | Access/Refresh token |
| argon2-cffi | 最新稳定 | 密码哈希（优于 bcrypt） |
| opentelemetry-sdk | 最新稳定 1.x | trace |
| structlog | 最新稳定 | 结构化日志 |

### 2.3 数据层

| 组件 | 锁定版本 | 说明 |
|------|---------|------|
| PostgreSQL | `18.x` | 原生异步 I/O（索引放不下内存时扫描快 30-40%） |
| pgvector | `0.8.7` | HNSW + `iterative_scan` |

### 2.4 基础设施

| 组件 | 选型 | 说明 |
|------|------|------|
| 沙箱隔离 | gVisor `runsc` | Phase 2 演进至 Kata Containers |
| 容器运行时 | Docker + runsc runtime | |
| 任务调度 | Hatchet（自托管，MIT） | 需适配层隔离，见 §6.2 |
| 对象存储 | S3 兼容 | 知识库/沙箱产物/checkpoint 归档 |
| 缓存/总线 | Redis `8.1.0` | |
| 可观测性 | OpenTelemetry + Prometheus + Grafana + Sentry | |
| 部署 | Docker Compose（MVP）→ K8s（Phase 2） | |

### 2.5 成本基线（MVP 阶段）

| 项| 月成本 |
|----|--------|
| 应用服务器（4c8g） | ¥200-400 |
| PostgreSQL（2c4g，托管） | ¥300-600 |
| Redis（1g） | ¥50-100 |
| 沙箱节点（按需，见下） | ¥0-200 |
| 对象存储+ CDN | ¥50-100 |
| **合计（不含AI 调用）** | **¥600-1400/月** |

沙箱成本临界点：单 Firecracker 节点自托管，在 2000 sandbox-hours/月时比最便宜托管方案省 66%，5000+ 时省 79-87%（计入运维人力后交叉点约 1500-2500 h/月）。**MVP 阶段沙箱用量低，直接用现有应用节点跑 gVisor，不单独采购。**

---

## 3. 多租户隔离方案

### 3.1 账套号体系

每个租户有两套标识，职责分离：

| 标识 | 格式 | 用途 | 示例 |
|------|------|------|------|
| `tenant_id` | UUID v4 | 内部主键，数据库关联 | `a3f2c8e1-...` |
| `tenant_code` | `AC-` + 8位Base32 | 对外账套号，客服/工单用 | `AC-8F3K2M9W` |

**为什么两套**：`tenant_id` 是 UUID，不可读、不含信息，出现在日志/工单里无法定位；`tenant_code` 可读、可口述、客户能报出来，但不能用于数据库关联（可被猜测/枚举）。两者在 `tenants` 表双向唯一约束。

### 3.2 三层防护

```
+---------------------------------------------------------------+
| 校验层：越权自动化测试                                        |
|  - pytest 集成测试（应用层）                                  |
|  - pgTAP（数据库层）                                         |
|  - 进 CI，失败即阻断发布                                     |
+---------------------------------------------------------------+
| 查询层：强制显式 tenant_id                |
|  - Repository 层签名强制带 tenant_id                          |
|  - SQL 中显式 WHERE tenant_id = :tenant_id                    |
|  - 目的：查询计划可见 + RLS 之外的纵深防御                     |
+---------------------------------------------------------------+
| 连接层：PostgreSQL RLS（不可绕过）                            |
|  - 每请求事务开始 SET LOCAL app.current_tenant = :tenant_id  |
|  - ENABLE + FORCE ROW LEVEL SECURITY                          |
|  - USING (tenant_id = NULLIF(current_setting(                 |
|             'app.current_tenant', true), '')::uuid)          |
+---------------------------------------------------------------+
```

**为什么三层都要**：每层都有独立的失败模式。

- 只做连接层（RLS）→ 查询计划可能不理想，且排查时看不到过滤条件（可观测性差）
- 只做查询层（应用层 WHERE）→ 漏一处即跨租户泄露，且**不报错**（沉默逻辑错误，最致命）
- 只做校验层 → 测试无法覆盖全部路径
- 三层一起 → 任一层失效仍有兜底

### 3.3 四条硬规则（违反即阻断发布）

**规则 1：必须 `FORCE ROW LEVEL SECURITY`**

```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE  ROW LEVEL SECURITY;  -- 缺这行=没开
```

只写 `ENABLE` 时，**表owner 依然能看到全部数据**——不报错、不告警、静默绕过。而表 owner 恰恰是应用最可能使用的连接身份。

**规则 2：策略里禁用 PL/pgSQL 函数**

```sql
-- 正确（内联式，零开销）
USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)

-- 错误（170倍性能灾难）
USING (tenant_id = app_current_tenant())
-- PL/pgSQL 函数无法内联；未标 STABLE 时是 VOLATILE，
-- 会对每一行调用一次 → 索引失效 → 200 万行顺序扫描
```

实测（PostgreSQL 17.10，200 万行 invoices / 1000 租户，索引 `(tenant_id, issued_on)`）：

| 策略写法 | 最大租户 COUNT | 相对开销 |
|---------|---------------|---------|
| `NULLIF(current_setting(...), '')::uuid` | 11.0 ms | 1x（基准） |
| SQL 函数（可内联） | 15.0 ms | 1.4x |
| PL/pgSQL 函数（默认 VOLATILE） | **1,877 ms** | **170x** |
| PL/pgSQL 函数（显式 STABLE） | 14.5 ms | 1.3x |

注意：**中位租户（只有 534 行）也同样受害**（1,860 ms）。小租户不因为行数少就免灾。

**规则 3：必须 `SET LOCAL`，不能 `SET`**

```sql
SET LOCAL app.current_tenant = '...';  -- 正确：事务作用域，提交即失效
SETapp.current_tenant = '...';         -- 错误：会话作用域，连接池复用时泄漏给下一个用户
```

PgBouncer transaction 模式下，`set_config` 第三个参数必须传 `true`。

**规则 4：视图必须显式 `security_invoker`**

```sql
CREATE VIEW v_projects WITH (security_invoker = true) AS SELECT * FROM projects;
```

PG 15+ 的视图默认以 owner 权限运行，会绕过 RLS。

### 3.4 迁移模板必须内建 RLS

**每张新表都要手工加策略，漏加即失去隔离。** 唯一可靠的防漏办法是在 Alembic 迁移模板里让"新建表"和"启用 RLS"在物理上无法分离：

```python
# app/db/mixins.py —— 所有租户表 Model 必须继承
class TenantScopedMixin:
    @declared_attr
    def __table_args__(cls):
        return (
            Index(f"idx_{cls.__tablename__}_tenant_created",
                  "tenant_id", "created_at"),
            # 强制 RLS，表定义与策略绑定，不可分离
            ...
        )
```

迁移模板中，租户表统一走 `create_tenant_table()` 助手，该助手内部强制 `ENABLE` + `FORCE` + 创建策略。

### 3.5 越权响应语义：统一 404，不返回 403

**PRD P0 验收标准第 12 条**：「A 租户尝试访问 B 租户的任务或文件 → 访问被拒绝；记录安全日志；**不泄露 B 租户任何数据存在性**」。

这带来一条容易被忽略的硬约束：**跨租户访问必须返回 404 Not Found，不能返回 403 Forbidden。**

原因：403 本身就在泄露信息。攻击者可通过响应码差异做资源枚举——403 说明"该 ID 存在但你无权访问"，404 说明"该 ID 不存在"。用 403 等于提供一个可批量扫描的oracle，攻击者能据此测绘出其他租户的资源规模与 ID 分布。

```
资源属于当前租户  ->  200 OK
资源属于其他租户  ->  404 Not Found        ← 不可区分于"真的不存在"
资源不存在        ->  404 Not Found
未认证            ->  401 Unauthorized     （不泄露任何资源信息）
已认证但无权限    ->  403 Forbidden        （仅限"知道资源存在且属自己租户"的场景，
                                             如尝试删除只读资源，不涉及跨租户）
```

实现约束：

- Repository 层对`tenant_id` 不匹配与"记录不存在"**返回同一种结果**（抛同一个 `NotFound` 异常），不允许在服务层区分
- **RLS 已经天然满足这一点**：`SET LOCAL app.current_tenant='A'` 后查B 的记录，SQL 返回 0 行，服务层看到的就是"不存在"→自然抛 `NotFound`。这是采用 RLS 而非仅应用层过滤的额外收益
- 所有跨租户拒绝**必须记安全日志**（`audit_logs`，level=WARN，事件类型 `cross_tenant_denied`），但**日志中不记录目标资源的标题/名称/文件名**，只记录 ID 与租户对
- 禁止在任何错误消息、响应体、响应时间中体现"该资源在其他租户存在"

补充：必须防止**时序侧信道**。跨租户访问（走 RLS 后 0 行）与真实不存在（走索引未命中）的响应时间应有量级一致性，不应让攻击者通过响应时间差异区分。

### 3.6 fail-closed 语义

`app.current_tenant` 未设置时，策略求值为 `NULL`，查询返回 **0 行**（而非全部行）。这是**正确的安全默认**，但会让"忘记设置租户上下文"的 bug 表现为"列表页空了"而非报错。

**硬约束**：必须在 Repository 层检测 `current_setting('app.current_tenant', true)` 为空时记录显式告警日志（level=WARNING，tag=`tenant_context_missing`），并配告警规则。不能让它静默发生。

### 3.7 大租户升级路径

触发条件：单租户任一表超 1000 万行 → 评估升级到独立 Schema。

迁移流程（预留，MVP 不实施）：
1. 创建 `tenant_{code}` schema + 同构表
2. `INSERT INTO tenant_x.projects SELECT * FROM public.projects WHERE tenant_id = ?`
3. 校验行数一致
4. 连接路由表加分支：该租户走独立 schema
5. 保留 public 表 30 天后清理

---

## 4. 沙箱隔离详细设计

> **这是安全底线。** EvoFlow 用本地沙箱（自认安全性最低，可访问宿主机文件系统），在桌面单机场景风险有限；多租户 SaaS 场景下，跨租户逃逸= 产品级灾难。

### 4.1 威胁模型

必须假设攻击者存在。四条攻击路径：

| 攻击 | 场景 | 后果 |
|------|------|------|
| 提示注入 | 客户 A 在知识库埋"读取其他租户数据" | 跨租户数据泄露 |
| 恶意代码 | 客户 B 主动提交挖矿/反连代码 | 资源劫持、C2 通道 |
| 资源耗尽 | fork 炸弹/内存炸弹/死循环 | 打垮共享宿主，影响**所有**租户 |
| 数据外泄 | 沙箱内代码 POST 凭据到外部 | 密钥泄露 |

### 4.2 五层防护

```
+--L5 网络层---------------------------------------------------+
|  出网 default-deny + 租户级白名单                             |
|  DNS 限制到内部解析器（阻断 C2域名解析）                       |
|  沙箱网段与生产网段隔离                                       |
+--L4 资源层 ---------------------------------------------------+
|  cgroups v2: CPU配额 / 内存上限 / pids-limit / 磁盘配额      |
|  超限即杀（不是排队）                                         |
+--L3 凭据层 ---------------------------------------------------+
|  凭据不进环境变量（ps//proc/*/environ 可读）                   |
|  经 stdin 或一次性token 文件注入，任务结束立即销毁             |
|  每租户独立解密密钥（密钥分离，限制爆炸半径）                   |
+--L2 容器加固层 ------------------------------------------------+
|  --cap-drop=ALL  - 禁止 privileged  - --read-only rootfs     |
|  seccomp + AppArmor + user namespace                         |
|  可写路径仅 /workspace（临时卷）                               |
+--L1 隔离层（核心）---------------------------------------------+
|  gVisor runsc：用户态内核拦截 syscall                        |
|  宿主机内核攻击面 = 经审核的 syscall 最小子集                 |
|  攻击者必须逃出 Go 实现的 Sentry + 宿主内核双重边界           |
+-------------------------------------------------------------+
```

**纵深防御**：L1 不构成"绝对安全"。gVisor 自身有过CVE。所以 L2-L5 是强制的，不是可选的加固。

### 4.3 沙箱执行流程

```python
# app/services/sandbox/sandbox_service.py（示意，非最终实现）
async def execute(
    tenant_id: UUID,
    agent_id: UUID,
    runtime: str,          # python:3.13-slim / node:22-slim
    command: list[str],
    workspace_files: dict,  # 输入文件
    timeout_s: int = 300,
    egress_allowlist: list[str],
) -> SandboxResult:
    """在隔离沙箱中执行命令，返回结构化结果。"""

    # 1. 生成一次性凭据（不经环境变量）
    token = await issue_ephemeral_token(tenant_id, ttl_s=timeout_s)

    # 2. 拉起沙箱（runsc runtime）
    sandbox = await pool.acquire(
        runtime=runtime,
        limits=SANDBOX_LIMITS,          # cpu=2, mem=2GiB, pids=128, disk=2GiB
        network_policy=egress_allowlist, # default-deny
    )

    # 3. 注入工作区文件（只读输入，输出目录单独可写）
    await sandbox.write_files(workspace_files, mount="/workspace/in")

    # 4. 执行（stdin 传 token，env 中零凭据）
    result = await sandbox.exec(
        command,
        stdin=f"AGENT_TOKEN={token}",
        env={"PATH": "/usr/bin:/bin", "HOME": "/workspace"},  # 无任何密钥
        timeout_s=timeout_s,
    )

    # 5. 收集产物 + 立即销毁 token
    artifacts = await sandbox.collect("/workspace/out")
    await token.destroy()

    # 6. 销毁沙箱（进池化冷态，不保留租户数据）
    await pool.release(sandbox)

    return SandboxResult(
        exit_code=result.exit_code,
        stdout=result.stdout[-64_000:],   # 截断，防内存爆炸
        stderr=result.stderr[-64_000:],
        artifacts=artifacts,
        truncated=result.truncated,
    )
```

### 4.4 沙箱配置基线

```bash
docker run -d \
  --runtime=runsc \
  --name sandbox-$(uuidgen) \
  --network=sandbox-egress-net \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --security-opt seccomp=sandbox.json \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --memory=2g --memory-swap=2g \
  --cpus=2 --cpu-quota=200000 --cpu-period=100000 \
  --pids-limit=128 \
  --ulimit nofile=1024:1024 \
  --user 65534:65534 \
  -v /sandbox/work/{sandbox_id}/in:/workspace/in:ro \
  -v /sandbox/work/{sandbox_id}/out:/workspace/out:rw,noexec,nosuid \
  --label tenant_id={tenant_id} \
  --label agent_id={agent_id} \
  --label ttl_epoch={expiry} \
  {image} sleep infinity
```

**逐条说明为什么**：

| 参数 | 防什么|
|------|--------|
| `--runtime=runsc` | L1 隔离：用户态内核拦截 syscall |
| `--cap-drop=ALL` | L2：Agent 不能获得任何 Linux capability |
| `--security-opt=no-new-privileges` | L2：禁止 setuid 程序提权 |
| `--security-opt seccomp` | L2：即使绕过 gVisor，仍有 syscall 白名单 |
| `--read-only` | L2：镜像层不可篡改（防持久化后门） |
| `--tmpfs /tmp:noexec,nosuid` | L2：/tmp 不可执行、不可 setuid |
| `--memory=2g --memory-swap=2g` | L3：禁swap，内存超限直接 OOM-kill沙箱 |
| `--cpus=2 --cpu-quota` | L3：防 CPU 占满宿主 |
| `--pids-limit=128` | L3：**防 fork 炸弹**（最容易被忽略的一条） |
| `--ulimit nofile` | L3：防 fd 耗尽 |
| `--user 65534` | L2：非 root（nobody）|
| `in:ro` / `out:rw,noexec` | L2：输入不可改，输出不可执行 |
| `--label tenant_id` | 运维：紧急时可定位并批量 kill 某租户全部沙箱 |
| `--label ttl_epoch` | 运维：崩溃恢复时清理孤儿沙箱 |

### 4.5 出网策略

```yaml
# app/services/sandbox/egress_policy.yaml
default: deny

allow:
  - host: api.openai.com
    port: 443
    reason: "LLM API (BYOK 客户自带Key 时不需要)"
  - host: api.deepseek.com
    port: 443
  - host: pypi.org
    port: 443
    reason: "包管理器（若允许动态安装依赖）"
  - host: files.pythonhosted.org
    port: 443
    reason: "包下载"
  - host: registry.npmjs.org
    port: 443

dns:
  resolvers: ["10.0.0.2"]   # 内部解析器，仅解析白名单域名
  # 非白名单域名返回 NXDOMAIN，阻断 C2 域名解析

deny_always:
  - "169.254.169.254"   # 云厂商元数据服务（凭据窃取经典路径）
  - "metadata.google.internal"
  - "10.0.0.0/8"        # 内网（防止横向移动）
  - "172.16.0.0/12"
  - "192.168.0.0/16"
  - "127.0.0.1"
```

**租户级白名单**：企业客户可申请追加自己的 API 端点（如自己的 ERP API），走安全中心审批。

### 4.6 沙箱池生命周期

| 阶段 | 时长 | 动作 |
|------|------|------|
| 冷启动 | — | 从镜像池取（预热镜像，启动 50-150ms） |
| 活跃 | ≤ timeout_s | 执行任务 |
| 冷却 | 5 分钟 | 归还池前清空 workspace；**不做内存快照**（避免跨租户数据残留） |
| 销毁 | — | workspace 全量擦除后销毁 |

**孤儿沙箱清理**：每 60 秒扫描 `--label ttl_epoch < now` 的容器并强制销毁。应对 worker 崩溃导致沙箱泄漏。

**不做内存快照**：Firecracker 的 snapshot/restore 能把冷启动压到 28ms，但跨租户复用快照有数据残留风险。MVP 阶段不用。

### 4.7 镜像管理

| 项 | 策略 |
|----|------|
| 基线镜像 | `python:3.13-slim-bookworm`、`node:22-slim-bookworm` |
| 客户自定义镜像 | **MVP 不支持**（自定义镜像是攻击面，需深度审计） |
| 依赖安装 | 预装进镜像；沙箱内动态 `pip install` 默认禁用（可按租户开） |
| 镜像扫描 | CI 阶段 `trivy` 扫描，HIGH/CRITICAL 漏洞阻断发布 |
| gVisor 兼容验证 | **每个镜像必须在 runsc 下跑通验证脚本**（syscall 覆盖缺口，见 §10） |

### 4.8 已知限制（必须告知）

1. **syscall 覆盖约 60%**：gVisor 只实现部分 syscall。`node`、`pysqlite3`、某些 `npm` 生命周期脚本可能失败。缓解：换用 gVisor 官方验证过的镜像组合
2. **I/O 密集场景 10-40% 性能开销**：Agent 场景 I/O 占比高（读文件、HTTP 调 LLM），实际影响 10-20%
3. **无 GPU**：沙箱内不能 GPU 推理（当前不需要）
4. **无状态跨沙箱**：沙箱销毁后工作区丢失，需要长任务产出必须显式 `collect` 到对象存储
5. **gVisor 自身有 CVE 历史**：不构成"绝对安全"，必须靠 L2-L5 纵深防御

---

## 5. 核心功能技术实现

### 5.1 Goal 长任务：后台挂起 + 断点恢复

**结论：可行。**

#### 架构

```
用户创建 Goal
     |
     v
[API 层] 写 goals 表 -> enqueue 到 Hatchet -> 立即返回 goal_id
     |                （不等任务完成）
     v
[Scheduler] Hatchet worker 拾取
     |
     v
[Agent Worker] LangGraph 图执行
     |
     +--> 每个节点执行后 --> Checkpointer 写 PostgreSQL (langgraph_checkpoints)
     |                        checkpoint_ns = goal_id
     |
     +--> 节点执行时 --> 发事件到 Redis Streams
     |                    goal:events:{tenant_id}:{goal_id}
     |
     +--> 遇到审批 --> interrupt() 暂停，等待 Command(resume=...)
     |
     +--> 工具调用 --> 沙箱执行（ADR-004）
     |
     v
[孤儿巡检器]每 30 秒扫 checkpoint，捞出超时的 running run并恢复
     |
     v
[SSE 端点] 读 Redis Streams -> 推给前端（支持 Last-Event-ID 续传）
```

#### 断点恢复的实现

```
Worker 崩溃:
  t=0   节点1 执行 -> checkpoint v1 落盘
  t=10  节点2 执行 -> checkpoint v2 落盘
  t=25  节点3 执行 -> 业务数据写入成功
  t=26  [崩溃] 进程被 OOMKill，checkpoint v3 未落盘
         → 数据库中 run 状态仍为 running（孤儿）

恢复:
  t=1800 孤儿巡检器发现最后心跳超 30 分钟 -> 重新 enqueue
         LangGraph 从 checkpoint v2 恢复 -> 重放节点3
         节点3 的幂等键 (goal_id, node_name) 已存在 -> INSERT ... ON CONFLICT DO NOTHING
         → 业务数据仍是 1 条，不是 2 条   [断言通过]
```

#### 五条硬约束

1. **节点内业务写入必须幂等**（最高优先级）。checkpoint 与业务数据不在同一事务，"业务成功但 checkpoint 未落盘"必然发生。幂等键 = `thread_id + node_name + attempt_ordinal`
2. **孤儿巡检不可省**。worker 崩溃后 run 永久 `running` 是可用性灾难。巡检阈值 30 分钟心跳
3. **checkpoint 表膨胀控制**。活跃 run 全量保留；终止 run 只留最近 3 个 checkpoint 或 7 天后归档到对象存储
4. **`thread_id` 必须等于 `goal_id`**。不能让 LangGraph 自己生成，否则用户刷新页面找不到自己的任务
5. **LLM 调用必须在节点内部**。LangGraph 的重放语义是"已完成节点不重跑"，所以 LLM 调用不能放在图外的循环里

#### 资源上限

| 项| 默认值 | 可按套餐调整 |
|----|-------|-------------|
| Goal 最长运行时长 | 24 小时 | 付费可延长 |
| Goal 最大节点数 | 1000 | |
| Goal 最大 LLM 调用次数 | 5000 | |
| Goal 最大花费 | ¥50 | 超额降级为只读模式 |
| 同时运行的 Goal（租户级） | 5 | |
| 同时运行的 Goal（全局） | 200 | |

**花费熔断**是必须的：一个陷入循环的 Agent 可以在 1 小时内烧掉几百元。必须在 graph 内每 5 个节点检查一次累计花费。

### 5.2 子 Agent 并发委派

**结论：可行（有条件，条件见下）。**

#### 并发控制四层

| 层级 | 控制项 | 默认 | 实现 |
|------|-------|------|------|
| 全局 | 同时运行 goal 数 | 200 | Hatchet worker 并发数 + Redis 信号量 |
| 租户级 | 同时运行 goal 数 | 5 | Redis 信号量（per-tenant key） |
| goal 级 | 子 Agent 并发数 | 5 | LangGraph 子图并发 + 信号量 |
| 沙箱级 | 每沙箱 CPU/内存/PID | 见 §4.4 | cgroups v2 |

**四层缺一不可**：只有全局限制会被单租户打爆；只有租户限制会被多租户总和打爆。

#### 超时控制（三级）

```python
# app/agents/delegation.py（示意）
MAX_SUBAGENT_DEPTH = 3# 委派深度上限，防递归委派
MAX_SUBAGENT_TOTAL = 10        # 单个 goal 的子 Agent 总数上限
DEFAULT_SUBAGENT_TIMEOUT = 300 # 单个子 Agent 超时

async def delegate(parent_run, tasks: list[Task]) -> list[SubResult]:
    if parent_run.depth >= MAX_SUBAGENT_DEPTH:
        raise DelegationDepthExceeded(...)  # 不静默截断，显式失败

    semaphore = await redis_semaphore(f"tenant:{parent_run.tenant_id}", limit=5)
    async with semaphore:
        results = await asyncio.gather(
            *[run_subagent(t, timeout=DEFAULT_SUBAGENT_TIMEOUT) for t in tasks],
            return_exceptions=True,   # 单个子 Agent 失败不影响兄弟
        )
    return results
```

**深度上限 3 层的原因**：每层委派都是指数级放大。深度 3、单层 5 个子 Agent，单个 goal 最多 125 个子 Agent。深度 5 就是 3125 个——共享资源瞬间打爆。必须在代码层硬限制，不是配置项。

#### SSE 进度回传

```
子 Agent 事件 --> Redis Stream (按 goal_id 聚合，seq 单调递增)
                      |
                      v
                SSE 端点读 Stream
                      |
                      v
              前端按 goal_id 过滤渲染
```

**关键设计**：所有子 Agent 的事件写**同一条 Stream**（按 goal 聚合），前端一条连接看全部进度。不按子 Agent 分流——那会导致连接数爆炸（HTTP/1.1 下浏览器 6 连接硬上限）。

事件类型：
```
goal.started / goal.progress / goal.tool_call / goal.tool_result
subagent.started / subagent.progress / subagent.completed
goal.approval_required / goal.approval_resolved
goal.completed / goal.failed / goal.cancelled
```

**条件说明（为什么是"有条件可行"）**：

- 若客户要求 50+ 并发子 Agent，需扩容 worker 节点 + 沙箱节点，成本线性上升
- 深度 3 层是架构限制。若产品要求"AI 自主规划并无限委派"（EvoFlow 的 Agent Teams），需要在深度 3 处引入**人工确认节点**——不能让 AI 自己决定无限往下派

### 5.3 智能体员工"上班"调度

**结论：可行。**

#### 三段式架构

```
定时触发(Hatchet cron)
     |
     v
组织树定位(agents 表自引用 + 递归 CTE)
     |
     v
启动 Agent run(goal_id, agent_id, trigger=cron)
     |
     v
派生与汇总:
  - 父 Agent 的 run 完成后 -> 子 Agent 产出并入父 Agent 汇总
  - 子 Agent run -> ancestor_run_id 字段关联到父 run
     |
     v
审批流(interrupt -> Command(resume) 携带修改)
```

#### 组织树查询

```sql
-- 查某员工的所有下属（含层级深度）
WITH RECURSIVE org_tree AS (
  SELECT id, parent_id, name, 1 AS depth
    FROM agents WHERE id = :root_agent_id
  UNION ALL
  SELECT a.id, a.parent_id, a.name, t.depth + 1
    FROM agents a
    JOIN org_tree t ON a.parent_id = t.id
   WHERE t.depth < :max_depth          -- 必须有，否则循环引用会死循环
)
SELECT * FROM org_tree ORDER BY depth, name;

-- 权限收敛：子 Agent 有效权限 = min(自身权限, 所有祖先权限)
WITH RECURSIVE chain AS (
  SELECT id, parent_id, permission_level, 0 AS depth
    FROM agents WHERE id = :agent_id
  UNION ALL
  SELECT a.id, a.parent_id, c.permission_level, c.depth + 1
    FROM agents a JOIN chain c ON a.id = c.parent_id
   WHERE c.depth < :max_depth
)
SELECT MIN(permission_level) AS effective_permission FROM chain;
-- permission_level: viewer=1 < member=2 < admin=3 < owner=4
```

#### 审批流

```
小李(财务): 生成账单 -> interrupt()
     |
     v
run.status = waiting_approval
approvals 表: { id, goal_id, agent_id, approver_id, payload, status=pending, created_at }
     |
     v
通知老板（站内 + 邮件）
     |
     v
老板操作:
  -批准      -> Command(resume={"action":"approve"})
  - 拒绝      -> Command(resume={"action":"reject","reason":"..."})
  - 批准并修改 -> Command(resume={"action":"approve","amount":9800})  [核心语义]
     |
     v
LangGraph 从暂停点继续，带修改后的上下文
```

**"带修改恢复"是审批流的核心语义**。不是简单的批准/拒绝二分。老板说"金额改成 9800 再发"，系统要能从暂停点继续且使用修改后的值。这是选 LangGraph interrupt 而非状态机表的关键理由。

#### 六条硬约束

1. **审批等待必须有超时兜底**（7 天）。超时 → run 标记 `expired` + 通知。**不允许永久 `waiting_approval`**
2. **必须防止组织树循环引用**。设 parent 时校验"目标祖先链不含自己"；递归 CTE 额外设 `max_depth = 10`
3. **员工停用在途任务**：MVP 采用"跑完当前任务 + 新任务不再派发"，语义最安全
4. **权限必须收敛而非放大**：子权限 = min(自身, 所有祖先)。用 `MIN()` 一句搞定
5. **循环依赖兜底**：图编排层设全局最大迭代次数 20，超出标记 `abnormal` + 告警
6. **组织树查询必须有 `parent_id` 索引**

#### 成本归集

每个 Agent run 独立记 `agent_id`，费用按 run 归集：

```sql
SELECT a.name AS agent_name,
       SUM(u.input_tokens)  AS input_tokens,
       SUM(u.output_tokens) AS output_tokens,
       SUM(u.cost_cents) / 100.0 AS cost_cny,
       COUNT(DISTINCT u.goal_id) AS task_count
  FROM usage_records u
  JOIN agents a ON a.id = u.agent_id
 WHERE u.tenant_id = :tenant_id
   AND u.created_at >= :start AND u.created_at < :end
 GROUP BY a.name
 ORDER BY cost_cny DESC;
```

这直接回答老板的问题："市场专员小王的成本最高，值不值？"

---

## 6. 流式与事件流

### 6.1 传输方案：SSE

**结论：SSE，不引入 WebSocket。**

理由详见 ADR-002。核心决定性因素是 `Last-Event-ID` —— Goal 长任务跑 3 小时，用户手机必然断网重连，SSE 的规范级重连+续传是决定性优势；WebSocket 的重连质量完全取决于我们自己写的代码。

### 6.2 Redis Streams 事件总线

```
所有 worker/Hatchet/LangGraph 节点
            |
            v
    XADD goal:events:{tenant_id}:{goal_id}
            |  { seq: <单调递增>, type: "...", payload: {...}, ts: ... }
            v
    Redis Stream (MAXLEN ~ 10000,近似裁剪)
            |
            +--> SSE 端点 XREAD（带 last_event_id）
            +--> 费用聚合消费者（消费组 A）
            +--> 可观测性消费者（消费组 B）
            +--> 审计消费者（消费组 C）
```

**多消费者组**：一个Stream 多个消费组，各组独立消费，互不干扰。

**Seq 生成**：必须单调递增且可比较。用 Redis `INCR goal:seq:{tenant}:{goal}` 分配，不用 Stream 自身 ID（Stream ID 是时间戳，与同毫秒事件排序不稳定）。

### 6.3 SSE 四个必踩的坑

| 坑 | 现象 | 解法 |
|----|------|------|
| **Nginx 缓冲** | 流式完全失效，结束时一次性返回 | `X-Accel-Buffering: no` + `proxy_buffering off` |
| **Cloudflare 100s 空闲超时** | Agent 调工具时 90s 无输出，连接被静默掐断 | 每 30 秒发 `: keepalive\n\n` 注释行|
| **ALB 60s 空闲超时** | 同上 | 目标组调至 300s |
| **HTTP/1.1 六连接限制** | 多个任务各开一条流后浏览器拒绝新连接 | **单条聚合 SSE 连接 + 服务端多路复用**；全站 HTTP/2 |

```nginx
# Nginx 参考配置
location /api/v1/ {
    proxy_pass http://api_upstream;
    proxy_http_version 1.1;

    # SSE 必需
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;

    # 超时
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    # 心跳透传（不缓冲 : keepalive 注释行）
    proxy_pass_header X-Accel-Buffering;
    add_header X-Accel-Buffering no;
}
```

### 6.4 单条聚合连接设计

前端**只开一条 SSE 连接**（连接 `/api/v1/events/stream`），服务端按用户订阅的所有 goal 做多路复用：

```javascript
// apps/web/src/lib/event-stream.ts
const stream = new EventSource('/api/v1/events/stream', {
  withCredentials: true,
});
// 浏览器自动重连 + 自动带 Last-Event-ID，无需手写重连逻辑

stream.addEventListener('goal.progress', (e) => {
  const { goalId, ...data } = JSON.parse(e.data);
  store.dispatch(goalProgressReceived({ goalId, data }));
});
```

**服务端**：维护 `订阅集合(user_id) -> Set[goal_id]`，一个 Stream 读取循环 + 按订阅过滤分发。这是把"每个任务一条连接"压缩成"每个用户一条连接"。

---

## 7. 数据模型概览

> 具体 DDL 属Phase 2。此处只给表清单与关键约束。

### 7.1 租户与身份

| 表 | 关键字段 | 约束 |
|----|---------|------|
| `tenants` | id, code(UNIQUE), name, plan, status | code 格式 `AC-`+8位Base32 |
| `users` | id, email(UNIQUE), password_hash, status | 全局账号，可属多租户 |
| `tenant_members` | tenant_id, user_id, role | UNIQUE(tenant_id, user_id) |
| `credentials` | tenant_id, kind, ciphertext, nonce | **每租户独立解密密钥** |

### 7.2 Agent 核心

| 表 | 关键字段 | 约束 |
|----|---------|------|
| `agents` | id, tenant_id, parent_id, name, permission_level, schedule_cron, status | INDEX(parent_id)；循环引用校验 |
| `goals` | id(=thread_id), tenant_id, created_by, status, budget_cents, spent_cents | status: pending/running/waiting_approval/completed/failed/cancelled/expired |
| `agent_runs` | id, goal_id, agent_id, ancestor_run_id, status, started_at, ended_at | 成本归集维度 |
| `approvals` | id, goal_id, approver_id, payload, status, timeout_at | status: pending/approved/rejected/expired |
| `subagent_runs` | id, parent_run_id, agent_id, depth, status | depth <= 3 |

### 7.3 检查点与队列

| 表 | 说明 |
|----|------|
| `langgraph_checkpoints.*` | LangGraph 内部表，**不手工改动 schema** |
| `hatchet.*` | Hatchet 内部表 |
| `usage_events` | 费用事件流（幂等键 `request_id`） |
| `usage_records` | 小时聚合（UNIQUE(request_id) 防重复计费） |

### 7.4 治理

| 表 | 说明 |
|----|------|
| `audit_logs` | **append-only**（REVOKE UPDATE/DELETE） |
| `dead_letters` | 死信队列 |
| `usage_daily` | 日聚合，看板查询 |

### 7.5 索引策略

**原则**：每张租户表建 `INDEX(tenant_id, created_at DESC)`。理由：

- RLS 策略产生 `tenant_id = ?` 条件，复合索引让 `tenant_id` 成为 Index Cond
- 绝大多数查询是"某租户的最近 N 条"
- 避免为选择性低的字段单独建索引（MVP 阶段不过度优化）

**pgvector 表**额外需要：

```sql
CREATE INDEX idx_kb_chunks_embedding
  ON kb_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
-- 必须：每租户表的 HNSW 索引是全租户共享的，靠 RLS + 显式 tenant_id 过滤
```

**注意**：HNSW 索引本身不分租户。这意味着一个超大的租户可能主导检索性能。缓解：MVP 阶段百级租户无问题；单租户向量数超 500 万时，评估该租户独立索引/独立 schema。

---

## 8. 图标库锁定（P0 绝对规则）

### 8.1 锁定结论

```
图标库：lucide-react
版本：  1.57.0（精确锁定，禁止 ^ / ~）
许可：  ISC（商用免署名）
范围：  1500+ 图标（1,778 独立概念），24x24 网格，stroke=currentColor，fill=none
stroke-width：1.5（设计侧锁定，与 1px 边框语言协调）
尺寸规范： 行内 16px / 按钮与导航 20px / 独立图标 24px
引入：  逐个具名import（依赖 tree-shaking）
例外：  品牌 logo 走 Simple Icons（CC0），限定 components/brand/，不与 UI 图标混排
```

**全项目唯一图标来源。任何第二套图标库的 PR 一律拒绝。**

**与设计侧对齐结果**：架构与设计**独立选型得出同一结论（Lucide）**，无冲突。设计师提供的补充信息已回写：
- Lucide 1.0 已移除全部品牌图标（法律风险）。模型 logo（OpenAI/Anthropic/DeepSeek/智谱）需单独引 **Simple Icons（CC0）**
- 这是 P0「统一不混用」规则的**唯一例外**，且必须同时满足三条：①只在模型选择器等品牌展示场景使用；②限定独立目录 `components/brand/`；③**不与 Lucide UI 图标在同一视图并排出现**
- 尺寸与 stroke 规范以设计侧为准（stroke-width 1.5，非我原稿的 2）

### 8.2 九条硬约束

| # | 约束 | 审查方式 |
|---|------|---------|
| 1 | `package.json` 中图标依赖只有 `lucide-react` 一项（品牌 logo 的 Simple Icons 除外，见 §8.1） | `grep -E '"(lucide\|heroicons\|tabler\|phosphor\|radix\|react-icons\|iconify\|font-)' package.json` 断言仅一项 |
| 2 | **禁止 emoji 作为功能图标** | `grep -rP "[\x{1F300}-\x{1FAFF}\x{1F000}-\x{1F2FF}\x{2600}-\x{27BF}\x{FE0F}]" src/ docs/` 断言无命中 |
| 3 | 禁止内联手写 SVG 图标 | `grep -rn "<svg" src/` 仅允许 `components/brand/` 下的品牌 logo |
| 4 | 必须具名import | `grep -rn "import \* as .* from 'lucide-react'" src/` 断言无命中 |
| 5 | Emoji 仅允许在纯文本语境（用户生成内容） | 代码评审 |
| 6 | 不用 emoji 替代图标的状态（成功/失败/进行中） | 用 `CircleCheck` / `CircleX` / `LoaderCircle` |
| 7 | **图标必须先进 `semantic-icon-map.txt` 再写代码** | CI 跑 `scripts/verify-icons.sh`，见 §8.6 |
| 8 | **禁止以文档站作为可用性依据** | 见 §8.6 的陷阱说明 |
| 9 | 升级 lucide 版本必须重跑验证脚本 | 依赖升级流程强制项 |

### 8.3 正确用法

```tsx
// 正确
import { Bot, CircleCheck, CircleX, LoaderCircle, Search } from 'lucide-react';

<Bot className="size-5" aria-hidden />              {/* 装饰性 */}
<CircleCheck className="size-4 text-emerald-600" /> {/* 状态 */}

// 错误（全部违反 P0 规则）
import { FaRobot } from 'react-icons/fa';  // 违反约束 1（第二套库）
<span>{String.fromCodePoint(0x1F916)}</span>   {/* 违反约束 2（emoji 图标，U+1F916） */}
<svg viewBox="0 0 24 24">...</svg>          {/* 违反约束 3（手写 SVG）}
import * as Icons from 'lucide-react';      // 违反约束 4（破坏 tree-shaking）
```

### 8.4 覆盖率缺口的正确处理

Lucide 有 1500+ 图标（实包导出 3782 个 `declare const`，含命名空间变体），26 个功能模块够用但不是宽裕。**若实现中出现 > 20 个图标找不到，正确做法是把 lucide-react 整体替换为 Tabler Icons（5900+），而不是新增第二套依赖。** 违反"统一不混用"的任何变通方案都不可接受。

### 8.5 可导入性验证门禁（P0，阻断级）

**版本**：`lucide-react@1.57.0`（2026-10-15 实包验证）

**关键陷阱：查文档站会误判。** `lucide.dev/icons` 的HTML 页面会保留**已被移除的旧文件**——本次 `CircleHelp` 与 `Filter` 就是这种陷阱：**文件存在于仓库，但没有 PascalCase 导出**，import 会得到 undefined。只看文档站会误判为「可用」。

**唯一可靠的验证方法**：实包比对 `declare const` 导出列表。

```bash
# scripts/verify-icons.sh —— CI 门禁，失败即阻断发布
set -euo pipefail
npm pack lucide-react@1.57.0 --silent
tar -xzf lucide-react-1.57.0.tgz
DTS=package/dist/lucide-react.d.ts
fail=0
while read -r name; do
  [ -z "$name" ] && continue
  grep -q "declare const ${name}:" "$DTS" || { echo "ICON MISSING: $name"; fail=1; }
done < docs/semantic-icon-map.txt
exit $fail
```

**已验证不可用**（会导致构建失败）：

| 名称 | 原因 | 正确替代 |
|------|------|---------|
| `UploadCloud` | 1.0 改名 | `CloudUpload` |
| `ShieldQuestion` | 无该导出 | `ShieldQuestionMark` |
| `CircleHelp` | 文件存在但**无导出** | `BadgeQuestionMark` |
| `Filter` | 文件存在但**无导出** | `ListFilter` |
| `Building2` | 1.0 移除数字后缀 | `Building` |

**Lucide 1.0 已移除的旧名**（9 个，全部不可再用）：
`AlertTriangle`→`TriangleAlert` / `AlertCircle`→`CircleAlert` / `AlertOctagon`→`OctagonAlert` / `CheckCircle2`→`CircleCheck` / `XCircle`→`CircleX` / `BarChart3`→`ChartColumn` / `LineChart`→`ChartLine` / `PieChart`→`ChartPie` / `Loader2`→`LoaderCircle`

**已验证可用的产品语义图标**（承载产品语义，选型经设计师语义论证）：

| 语义 | 图标 | 选型理由 |
|------|------|---------|
| 智能体 | `Bot` | — |
| 员工岗位 | `Briefcase` | — |
| 值班 / 排班 | `CalendarClock` / `CalendarDays` | — |
| 知识库 | `Library` | — |
| 知识检索 | `Search` | — |
| 计费 | `Receipt` | — |
| 组织架构 | `Network` | — |
| 状态：成功 | `CircleCheck` | — |
| 状态：失败 | `CircleX` | — |
| 状态：进行中 | `LoaderCircle` | — |
| **等你确认** | **`Hand`**（举手） | **刻意避开全部 alert 系**。一旦建立「红=有问题」的映射，老板看到红色就紧张；「停下来问」不是故障而是协作 |
| **需授权** | **`LockKeyhole`** | 同理避开 warn 黄。高难度岗位的前置条件不应用警告色表达 |

### 8.6 设计约束（与项目总监规则一致）

- **禁止紫色→粉色渐变方案**
- 图标与文字的 stroke 权重配对：字体 Light/Thin(300-) 配 1px 描边；Regular(400) 配 1.5-2px；Semibold/Bold(600+) 用 Filled/Solid 样式（本项目统一 outline，故Bold 场景用 Semibold 字体 + 2.5px stroke）

---

## 9. 安全清单（Checklist）

### 9.1 租户隔离

- [ ] 每张租户表 `ENABLE` + **`FORCE`** ROW LEVEL SECURITY
- [ ] 策略用内联式 `NULLIF(current_setting(...), '')::uuid`，**禁用 PL/pgSQL 函数**
- [ ] 每请求 `SET LOCAL app.current_tenant`（事务作用域）
- [ ] 应用连接角色**无** `BYPASSRLS`、**非** superuser
- [ ] 所有视图 `WITH (security_invoker = true)`
- [ ] 所有函数 `SECURITY INVOKER`（不是默认的 DEFINER）
- [ ] 每张租户表有 `INDEX(tenant_id, ...)`
- [ ] `tenant_context_missing` 告警规则已配置
- [ ] 越权测试套件进 CI（阻断级，见 §11）

### 9.2 沙箱

- [ ] `--runtime=runsc`
- [ ] `--cap-drop=ALL` + `--security-opt=no-new-privileges`
- [ ] `--read-only` + `--tmpfs /tmp:noexec,nosuid`
- [ ] `--pids-limit=128`（防 fork 炸弹）
- [ ] `--memory` + `--memory-swap` 相等（禁 swap）
- [ ] 出网 default-deny + 白名单
- [ ] DNS 限制到内部解析器
- [ ] 阻断云元数据地址（`169.254.169.254` 等）
- [ ] 沙箱网段与生产/DB 网段隔离
- [ ] **无任何凭据进入环境变量**
- [ ] 每租户独立凭据解密密钥
- [ ] 孤儿沙箱清理器（每 60 秒）
- [ ] 所有镜像经 `trivy` 扫描，HIGH/CRITICAL 阻断发布
- [ ] 所有镜像经 runsc 兼容验证

### 9.3 认证授权

- [ ] `argon2-cffi` 密码哈希（非 bcrypt）
- [ ] Access token短时效（15 分钟）+ Refresh token 轮换
- [ ] RBAC 四租户角色（owner/admin/member/viewer）+ 五全局角色
- [ ] **权限感知 Function Calling：过滤在发送给 LLM 之前完成**
- [ ] 平台管理员操作有独立审计记录

### 9.4 数据保护

- [ ] 审计日志 `REVOKE UPDATE, DELETE`（数据库层，非应用层自律）
- [ ] 凭据加密存储（AES-256）+ 每租户独立密钥
- [ ] **API Key 永不回显全文**（PRD P0）：写入后只存密文，任何接口不回传明文，仅显示末 4 位
- [ ] 传输全 TLS
- [ ] 敏感字段不进日志（Key/Token/密码）
- [ ] 租户数据导出 + 一键删除（合规）
- [ ] 对象存储路径含租户前缀 + 服务端加密
- [ ] **越权统一返回 404**（不泄露资源存在性，见 §3.5）
- [ ] 跨租户拒绝记安全日志，但日志不含目标资源名称

### 9.6 可观测性数据边界（PRD P0 承诺）

PRD P0 承诺：**「不记录模型调用内容」**——这是对客户的核心承诺，必须在架构层强制。

| 允许记录 | 禁止记录 |
|---------|---------|
| 模型名、token 数、延迟、费用、重试次数 | **Prompt 全文** |
| 工具名、参数**摘要**（类型+长度+脱敏后的枚举值）、结果状态码 | **工具返回内容全文** |
| Agent ID、goal ID、span 父子关系、错误码 | 用户上传文档内容 |
| 知识库检索的 chunk ID 与相似度分数 | 检索到的 chunk **原文** |

实现约束：

- OTel span 属性中**禁止**使用 `gen_ai.prompt` / `gen_ai.completion` 这类会承载内容的语义约定属性；只记录 `gen_ai.usage.input_tokens` / `output_tokens` / `gen_ai.request.model`
- 采样参数需传入 `prompt_hash`（内容哈希，非内容）用于去重与关联
- 错误日志中的 LLM 响应片段必须先脱敏（去除疑似 PII 与凭据模式串）
- **日志采集管道本身要做一次审计**：确认 OTel Collector 的 exporter 不会把 span attributes 全量落盘
- 沙箱 stdout/stderr 会被记录（用于调试），但必须在记录前过脱敏过滤器，且长度上限 64KB（见 §5沙箱流程中的 `stdout[-64_000:]`）

### 9.7 供应链

- [ ] 依赖精确锁版本（无 `^`/`~`）
- [ ] `pip-audit` + `npm audit` 进 CI
- [ ] 镜像 `trivy` 扫描
- [ ] 依赖许可审查（ISC/MIT/Apache/BSD 白名单；AGPL/SSPL 需法务）
- [ ] 沙箱镜像源固定 digest（非 `latest`）

### 9.8 限流与配额

- [ ] API 层限流（Redis 令牌桶，按租户+用户双维度）
- [ ] API 层配额检查（超额 429 + 升级引导）
- [ ] **任务层花费熔断**（长任务预算超限降级/终止）
- [ ] 沙箱并发上限（四层，见 §5.2）
- [ ] 上传大小/文件数限制

---

## 10. 性能目标与压测标准

### 10.1 服务端API

| 接口类型 | P50 | P95 | P99 |
|---------|-----|-----|-----|
| 普通 REST（列表/详情） | < 50ms | < 150ms | < 300ms |
| 写操作（创建/更新） | < 80ms | < 200ms | < 400ms |
| SSE 首字节（TTFB） | < 500ms | < 1s | < 2s |
| SSE 事件延迟（产生→到达前端） | < 200ms | < 500ms | < 1s |
| 向量检索（HNSW 10 万条1536 维） | < 5ms | < 15ms | < 30ms |

### 10.2 Agent 执行

| 指标 | 目标 | 说明 |
|------|------|------|
| TTFT（首token 时间） | < 2s | 不含 Agent 规划阶段 |
| 沙箱冷启动 P50 | < 200ms | gVisor runsc |
| 沙箱冷启动 P95 | < 500ms | |
| 子 Agent 并发 | >= 5/goal | 四层限流下 |
| Goal 恢复时间（崩溃后） | < 5 分钟 | 巡检间隔 30s + 恢复耗时 |
| Checkpoint 写入延迟 | < 100ms | 不应显著拖慢图执行 |

### 10.3 容量目标（MVP 阶段）

| 项 | 目标 |
|----|------|
| 租户数 | 100 |
| 并发用户 | 500 |
| 同时运行的 goal | 200 |
| 每日 LLM 调用 | 100 万次 |
| 沙箱并发 | 50（gVisor，单节点可支撑更多） |
| 数据库连接数 | API 20/worker × 4 + worker 10 × N + 巡检 2 |
| Redis 连接数 | < 100 |

### 10.4 压测标准（Phase 3 必做）

**必须覆盖的场景**：

1. **RLS 开销压测**：最大租户（26.7 万行）COUNT 与列表，断言 P95 < 20ms
2. **沙箱并发压测**：50 并发沙箱满负载，断言其他 API 的 P99 涨幅 < 10%（噪声邻居隔离）
3. **SSE 长连接压测**：500 条聚合 SSE 连接持续 30 分钟，断言：无内存泄漏（RSS 增长 < 10%）
4. **长任务稳定性**：模拟 3 小时任务（加速 100 倍），断言：无内存泄漏、无 checkpoint异常膨胀
5. **崩溃恢复压测**：随机 kill worker（10% 概率），断言：全部被巡检器恢复，无永久 `running`
6. **孤儿巡检压测**：kill 全部 worker，断言：30 分钟内全部 run 被标记或恢复
7. **费用归集准确性**：10 万次调用，断言：`usage_events` 与 `usage_records` 差额为 0（重投不重复计费）
8. **越权测试**：ADR-003 §Verification 的全部阻断级用例

**通过标准**：上述 8 项全过，且 API P99 在 §10.1 目标内。任何一项不过即阻断上线。

---

## 11. 越权测试套件（阻断级）

这是租户隔离的自动化验证，**必须进 CI，失败即阻断发布**。

```python
# tests/security/test_tenant_isolation.py（示意）
import pytest
from sqlalchemy import text

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"

@pytest.mark.blocking
async def test_cross_tenant_select_returns_nothing(db):
    """跨租户 SELECT 必须返回 0 行"""
    await db.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
    rows = await db.execute(text(
        "SELECT * FROM projects WHERE tenant_id = :t"), {"t": TENANT_B})
    assert rows.rowcount == 0, "跨租户读取成功——租户隔离失效"

@pytest.mark.blocking
async def test_cross_tenant_insert_rejected(db):
    """跨租户 INSERT 必须被 RLS 拒绝"""
    await db.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
    with pytest.raises(Exception):
        await db.execute(text(
            "INSERT INTO projects (tenant_id, name) VALUES (:t, 'x')"),
            {"t": TENANT_B})

@pytest.mark.blocking
async def test_missing_context_fails_closed(db):
    """无租户上下文时必须 fail-closed（返回 0 行，不是全部行）"""
    await db.execute(text("RESET app.current_tenant"))
    rows = await db.execute(text("SELECT * FROM projects"))
    assert rows.rowcount == 0, "无上下文时返回了数据——fail-open 是严重缺陷"

@pytest.mark.blocking
async def test_pool_no_context_leak(db_with_pool):
    """连接池不得泄漏租户上下文"""
    async with db_with_pool.acquire() as conn:
        await conn.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
        await conn.commit()
    async with db_with_pool.acquire() as conn2:
        rows = await conn2.execute(text("SELECT * FROM projects"))
        assert rows.rowcount == 0, "SET LOCAL 失效，会话作用域泄漏"

@pytest.mark.blocking
async def test_table_owner_cannot_bypass(db_owner_conn):
    """表 owner 也不能绕过（FORCE 必须生效）"""
    await db_owner_conn.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
    rows = await db_owner_conn.execute(text(
        "SELECT * FROM projects WHERE tenant_id = :t"), {"t": TENANT_B})
    assert rows.rowcount == 0, "表 owner 绕过了 RLS——FORCE 未生效"

@pytest.mark.blocking
async def test_view_respects_rls(db):
    """视图必须受RLS 约束（security_invoker）"""
    await db.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
    rows = await db.execute(text("SELECT * FROM v_all_projects"))
    assert all(r["tenant_id"] == TENANT_A for r in rows), "视图绕过了 RLS"

@pytest.mark.blocking
async def test_vector_search_tenant_isolated(db):
    """向量检索必须叠加租户过滤"""
    await db.execute(text(f"SET LOCAL app.current_tenant = '{TENANT_A}'"))
    rows = await db.execute(text("""
        SELECT tenant_id FROM kb_chunks
        WHERE category = :cat
        ORDER BY embedding <=> (SELECT embedding FROM query_vec LIMIT 1)
        LIMIT 10"""), {"cat": "restricted"})
    assert len(rows) == 10, "过滤不足 N 行——iterative_scan 未启用"
    assert all(r["tenant_id"] == TENANT_A for r in rows), "向量检索跨租户"
```

**阻断级用例清单**（任一失败即禁止发布）：

| # | 用例 | 对应风险 |
|---|------|---------|
| 1 | 跨租户 SELECT 返回 0 行 | 数据泄露 |
| 2 | 跨租户 INSERT 被拒 | 数据注入 |
| 3 | 无上下文 fail-closed | fail-open 导致全量泄露 |
| 4 | 连接池无上下文泄漏 | 跨用户越权 |
| 5 | 表 owner 不能绕过 | FORCE 未生效 |
| 6 | 视图受 RLS 约束 | 视图绕过 |
| 7 | 向量检索隔离 + 足量返回 | 向量层泄露 + 召回不足 |
| 8 | 沙箱内 `env` 无凭据 | 凭据泄露 |
| 9 | 租户 A 密钥解不开 B 的密文 | 密钥分离失效 |
| 10 | 审计日志不可 UPDATE/DELETE | 审计可篡改 |
| 11 | 权限感知 FC：LLM 看不到无权工具 | 越权工具暴露 |
| 12 | package.json 仅一个图标库 | 违反 P0 规则 |
| 13 | 源码无 emoji | 违反 P0 规则 |
| 14 | Goal 幂等：崩溃恢复后无重复副作用 | 重复扣款/发信 |
| 15 | 跨租户访问返回 **404** 而非 403 | 泄露资源存在性 |
| 16 | 日志/trace 中无 prompt 全文与工具返回全文 | 违反对客户的核心承诺 |
| 17 | API Key 接口永不回显全文 | 凭据泄露 |

前 14 条对应架构约束；第 15-17 条对应 PRD 的 P0 承诺（越权不泄露存在性、不记录模型调用内容、Key 永不回显），必须在同一套 CI 门禁中验证。

---

## 12. 不可行警告与高成本项

> 本节是给项目总监的明确风险告知。按"发现即不合格"的标准，以下问题不能含糊。

### 12.1 【最高风险】干净室重写的工作量被低估

**问题**：26 个功能模块的完整复刻，不是"实现 26 个功能"，而是"实现 26 个功能 × 多租户 × 安全 × 可观测"。

**量级估算**：

| 阶段 | 内容 | 人月|
|------|------|------|
| Phase 2-3 基础设施 | 多租户 + RLS + 沙箱 + 调度 + 事件流 + 治理层 | 6-8 |
| Phase 4-5 核心 Agent 能力 | 对话/Plan/Goal/子Agent/员工调度 | 8-10 |
| Phase 6 功能模块批量 | 剩余 18 个模块 | 10-14 |
| Phase 7 治理层深化 | SSO/费用/可观测性/安全中心完善 | 4-6 |
| **合计** | | **28-38 人月** |

**结论**：这不是 8-14 周的 MVP（知识库口径），是**6-9 个月**（团队 4-6 人）。请据此调整排期预期。

### 12.2 【高成本】沙箱的 syscall 覆盖缺口

**问题**：gVisor 只实现约 60% 的 syscall。`node`、`npm` 生命周期脚本、`pysqlite3`、部分 Python C 扩展在 runsc 下可能失败。这是**实测风险**，不是理论风险。

**影响**：若客户场景重度依赖 Node 生态或需要动态装包，gVisor 可能不够用。

**缓解**：
- Phase 2 必须**先跑镜像兼容 POC**（Python/Node 各10 个常用场景），再决定是否锁 gVisor
- 若 POC 失败率高，**升级到 Kata Containers**（microVM 硬件隔离 + 标准容器 API，API 层不变）

**明确告知**：这个决策**不可逆性中等**。从 gVisor 升到 Kata 只需换 runtime，但镜像需要重新验证。

### 12.3 【已修正】网页访问能力分三级，MVP 只做 L1 HTTP 抓取

> **本节已修正。** 初版写「MVP 只做客户自己授权的域名」，但这与 §14.1「竞品监控日报可留在 MVP 第一位」矛盾——竞品监控按定义要访问竞品官网，不是客户自有域名。修正后的完整方案见 [ADR-014](decisions/ADR-014-web-access-tiers.md)，本节为摘要。

**关键认知：网页访问不是一种能力，是三种成本与合规风险差一个数量级的能力。**

| 级别 | 能力 | 单次成本 | 内存 | 目标合规姿态 | MVP |
|------|------|---------|------|------------|-----|
| **L1** | 服务端 HTTP 抓取 + HTML 解析 | 10-50ms | 无状态 | 代客户抓公开页，需 robots/频率/UA 约束 | **是** |
| **L2** | 无头浏览器渲染（Playwright） | 0.3-2s | 300-500MB/实例 | 同 L1，可渲染 JS | 否 |
| **L3** | 登录态 / 客户自有系统操作 | 0.5-3s | 300-500MB/实例 | 客户显式授权 | 否 |

**竞品监控日报不需要 L2。** 企业官网/新闻/博客主体内容绝大多数是服务端渲染 HTML，L1 即可。L2 只在目标是 JS 重渲染 SPA 时需要，**且这类目标本就该显式标记为抓取失败**（见下G4）。

**用户复看裁定（推翻 C1 收窄）：L1 恢复第三方公开网页抓取，竞品监控日报为 MVP 岗位 #1。** 分级能力设计自始成立，G1-G4 护栏全部保留——**G1/G3 的定位是「约束平台行为」（不绕过 robots、不伪装浏览器），不是「取悦客户」**。

**L1 必须配套四条护栏**（缺一不可上线）：

| 护栏 | 内容 | 防什么 |
|------|------|--------|
| G1 robots.txt 合规 | 抓取前检查，`Disallow` 命中即跳过并记录 | robots 协议违规（法律风险） |
| G2 频率限制 | 单域名 ≥2s；单租户 ≤20 请求/分钟；全局 ≤200/分钟 | 压垮目标站→被封 IP |
| G3 UA 声明 | `OPCAgentAI/1.0 (+URL; contact=...)`，**不伪装成浏览器** | 身份隐瞒；被识别后可追溯 |
| **G4 失败显式化** | 抓取失败/被 robots 拒绝/内容为空 **必须进「我停下来过」板块，禁止返回空日报冒充成功** | **静默失败是竞品差评头号来源** |

**G4 是最重要的一条**。竞品监控最危险的失败模式不是「抓不到」，而是「抓不到但报告说今天没有异常」——老板会据此做决策。抓取失败必须是一等公民状态。

**合规姿态必须诚实**：代客户抓第三方网站 ≠ 客户抓自己授权的域名。L3 客户授权、风险可转移；**L1 我们是直接请求方，责任在我们这侧**。这个风险无法用技术消除，只能靠 G1-G4 + 服务条款明示来管理。**PRD 合规章节必须写明「本服务会代表您访问第三方公开网页」**，这一点 PM 需补。

**已排除的方案**：
- L2 一步到位：最高成本解决 20% 问题，且 **Chromium 在 gVisor 下 syscall 覆盖大概率失败**（ADR-004 §12.2），把未验证风险放进 MVP 不划算
- 竞品降级为「客户自有系统」：等于把岗位语义改掉，砍掉差异化最直观的岗位
- 客户自带数据 API Key：技术上干净但与「中小企业无 IT 运维能力」的用户画像（PRD §2.3）直接冲突

**副作用提醒 PM**：部分竞品监控会失败（目标站改版/加防护/要求登录），这是 G4 显式报告的内容。**这会拉低竞品监控的 TCR 天花板**（外部依赖不受我们控制）。建议 Go/No-Go 判据**按岗位分别设定**，不要一刀切。

### 12.4 【中等风险】LangGraph 版本仍在本演进

**问题**：LangGraph 1.x 已GA（checkpoint/durable execution 稳定），但 API 仍在演进（checkpoint schema 会变）。

**缓解**：锁定精确版本 + 适配层 + 升级前跑端到端验证（ADR-001 §Verification）。已在 ADR-007 记录为已知坑。

### 12.5 【中等风险】Hatchet 仍是 v0.x

**问题**：Hatchet v0.107.0（2026-09），7,949 stars，生产案例少于Temporal。API 破坏性变更风险真实。

**缓解**：必须写适配层（`app/services/scheduler/`），业务代码不直接 import Hatchet SDK。**Phase 2 就要跑降级路径 POC**（Redis Streams + 自研 scheduler，约 400 行），不要等到需要时才验证。

### 12.6 【不可行，明确排除】以下 EvoFlow 能力在 SaaS 形态下不做

| EvoFlow 能力 | 为什么在 SaaS 下不可行/不适用 |
|--------------|------------------------------|
| 访问宿主机本地文件系统 | 多租户下等于全租户文件泄露。**绝对禁止** |
| 本地模型推理 | 需要 GPU，成本结构完全不同（云 GPU 是持续成本而非一次性） |
| 桌面系统托盘常驻 | Web 形态无此概念 |
| 读取本地剪贴板/文件拖拽 | 浏览器权限受限且需用户授权，Web Notifications 替代 |
| 系统级文件锁 | 多租户共享文件系统下无意义 |
| 单机 SQLite 零配置 | 与多租户 + RLS 根本冲突 |

### 12.7 【成本提醒】沙箱规模化后的成本跃升

**问题**：MVP 阶段沙箱用量低，混跑在应用节点。但规模化后成本非线性上升。

| 月沙箱时长 | 自托管 vs 最便宜托管方案 |
|-----------|------------------------|
| 500 h | 自托管更贵（摊销不足）|
| 2000 h | 自托管便宜 66% |
| 5000 h | 自托管便宜 79-87% |
| 交叉点（计入运维人力）| 约 1500-2500 h/月 |

**结论**：MVP 阶段不单独采购。**Phase 2 达到 1500 h/月时重新评估**。

### 12.8 【成本提醒】治理层不是附属功能

**问题**：SSO/费用统计/可观测性/安全中心这5 个模块在 EvoFlow 中全空白，我们必须从零建。工作量约 4-6 人月（见 §12.1）。

**但这是差异化优势**：中小企业老板买 SaaS 最关心（1）钱花哪了（2）员工能不能用（3）安不安全。这三点恰好是 EvoFlow 的空白点。

**建议**：不要为了赶进度砍治理层。砍掉治理层的产品，企业客户不会买——功能再多也没用。

---

## 13. Phase 2 交付清单（给 PM与开发的交接）

### 13.1 必须锁死的版本

见 §2。开发必须用这些版本，Phase 2 的 `requirements.txt` / `package.json` 由架构师提供。

### 13.2 必须写进 Spec 的 P0 约束（汇总）

| # | 约束 | 来源 |
|---|------|------|
| 1 | 图标库只有 lucide-react@1.57.0，禁 emoji | ADR-006 / §8 |
| 2 | RLS 必须 FORCE + 内联式策略 + SET LOCAL | ADR-003 / §3.3 |
| 3 | 沙箱必须 runsc + cap-drop ALL + pids-limit + 出网 deny | ADR-004 / §4.4 |
| 4 | 凭据不进环境变量；每租户独立密钥 | ADR-010 / §9.4 |
| 5 | 图节点业务写入必须幂等 | ADR-007 / §5.1 |
| 6 | 权限过滤在发送给 LLM 之前 | ADR-010 |
| 7 | 审计日志 append-only（DB 层 REVOKE） | ADR-010 / §9.4 |
| 8 | SSE 必须禁Nginx 缓冲 + 30s 心跳 | ADR-002 / §6.3 |
| 9 | 委派深度 <= 3，全局迭代 <= 20 | ADR-009 / §5.2 |
| 10 | 递归 CTE 必须设 max_depth | ADR-009 / §5.3 |
| 11 | 越权统一返回 **404**（不泄露资源存在性） | PRD P0-12 / §3.5 |
| 12 | 不记录模型调用内容（仅记元数据+哈希） | PRD P0 / §9.6 |
| 13 | API Key 永不回显全文（只显末 4 位） | PRD P0 / §9.4 |

### 13.3 Phase 2 必须产出的 sidecar

| 产物 | 说明 |
|------|------|
| `openapi.yaml` | OpenAPI 3.0/3.1 规范，前端据此生成 TS 类型，后端据此实现。**无此文件不放行 Phase 2** |
| 迁移模板 | Alembic 模板内建 RLS（§3.4） |
| 沙箱镜像兼容 POC | Python/Node 各 10 场景（§12.2） |
| Hatchet 降级路径 POC | Redis Streams scheduler（§12.5） |
| 越权测试套件 | §11 全部 14 条 |
| ER 图 + 索引清单 | Phase 2 补充 |

### 13.4 待项目总监决策的事项

| # | 事项 | 我的建议 |
|---|------|---------|
| 1 | 开发排期按 6-9 个月还是压缩？ | 压缩则砍功能模块数，**不要砍治理层和安全** |
| 2 | 是否接企业微信/钉钉/飞书 IM？ | Phase 3 接飞书（文档开放），Phase 4 接企微 |
| 3 | 浏览器控制模块范围？ | MVP 只做客户自有域名授权 |
| 4 | 是否需要 Tauri 桌面壳？ | MVP 不需要，Phase 2 视本地模型需求再评估 |
| 5 | 沙箱节点是否独立采购？ | MVP 不采购，Phase 2 达 1500h/月时评估 |
| 6 | **F6 做简版还是延期？** | **做简版（F6-lite，1.5-2 人月），不做延期。** 详见 §14.1 |
| 7 | ~~平台代付资金池风控~~ **已作废：纯 BYOK 后平台不经手资金，问题不复存在（ADR-019）** | **站得住，但有3 个前置条件必须写进 PRD。** 详见 §14.3 |

---

## 14. PM 四项技术输入的结论（Phase 1.5 补充）

> 本节回应 PRD §7.3 F6、§10.2 计费、§7.3 F2、§9.1 形态四个方向的技术结论。
> 详细设计见 ADR-011/012/013。

### 14.1 F6 长任务引擎：Effort 重估与分期建议

**Effort=8 人月偏高40-60%。F6-full 合理区间 5-6 人月**（含阈值调参余量）。

分解依据（关键：**部分工作已在 Phase 2-3 基础设施预算内，不应重复计入 F6**）：

| 工作项 | 归属 | 人月 |
|--------|------|------|
| 断点续跑（Checkpointer） | 已在基础设施（ADR-007） | 0（已计） |
| 事件流 / SSE 进度推送 | 已在基础设施（ADR-002/008） | 0（已计） |
| `task_steps` 业务状态机 + 汇报对接 | F6 增量 | 1.0 |
| 无进展检测（四信号 + 阈值调参） | F6 增量 | 1.5 |
| 步骤数预估 | F6 增量 | 0.5 |
| 中止 + 协作式取消 | F6 增量 | 0.5 |
| 幂等键贯穿 | F6 增量 | 0.5 |
| 岗位模板步骤定义 | F1 部分 | 0.5 |

**结论：不是「F6 做简版」或「F6 延期」的二选一，而是分期：**

| 方案 | 内容 | 人月 | 覆盖验收标准 |
|------|------|------|---------|
| **F6-lite**（建议 MVP 用） | 断点续跑 + 中止 + 步骤预估 + 简版熔断（仅重复工具序列检测） | **1.5-2** | 「40 步崩，第 26 步续跑，成果费用保留」+「熔断不产生额外费用」 |
| **F6-full**（Phase 2） | 四信号融合 + 软阈值人工确认 + 岗位级阈值调参 | 3-4 | 全部 |

**F6-lite 已能挡住 Manus 的两类差评**（半成品交付 + 死循环烧额度），因为「重复工具序列检测」是确定性零误判的。**绝不能砍断点续跑**——那是对撞 Manus 差评的核心能力。

**MVP 岗位难度递进对 F6 有利**（技术背书）：前4 个岗位（竞品监控/周报汇总/催办/发票核对）步骤少、外部副作用低，F6-lite 足够；只有第 5 个「电商订单录入」（20-40 步、高外部副作用）才需要 F6-full。**这给了天然的推广节奏**：MVP 用 F6-lite 拿真实数据，Phase 2 做电商岗位时补 F6-full。

**为什么不做 PM 的降级方案「AI 生成方案 + 人工逐步确认」**：技术代价极小（复用 `interrupt`，1-2 人周），但 **HITL 率从 ≤2% 变成 100%，直接违反 PRD §8.4 的 Go/No-Go 判据**，且「雇 AI 员工」变「AI 帮你想」，ROI 论证与定价论证同时崩塌。**降级不是技术选择，是换产品。**

**无进展检测的设计要点**（ADR-011 详述）：

四信号分层，替代固定步数上限：

| 信号 | 判定 | 强度 |
|------|------|------|
| S1 重复工具序列哈希命中 | 立即熔断 | 确定性，零误判 |
| S2 产出物增量连续 N 步为 0 | 熔断 | 强 |
| S3 无外部副作用连续 N 步 | 熔断 | 中 |
| S4 状态指纹 | 辅助 | 弱（易骗过）|

- **阈值由岗位模板声明**（`expected_idle_steps`，默认 5），不硬编码——「下载 100 个页面」每步产出物相同是正常的，「读一份 Excel」第 3 步没产出就是卡死
- **软阈值用 `interrupt()` 拉人确认**，不是直接熔断。这是 HITL 的正确用途
- **熔断判定必须在下次 LLM 调用之前**，否则熔断后仍产生费用，违反验收标准
- **检测窗口状态必须落盘**，否则崩溃重启后归零，死循环重复触发 N 次

### 14.2 计费：预算校验落点与防超卖 —— **[已作废 2026-10-15]**

> **作废原因**：决策变更二删除平台代付，改为纯 BYOK + 线下收款。平台不经手资金、无「平台余额」概念，预占-确认-释放两阶段账本（credit_reservations / credit_ledger）失去前提，三张 credit 表已从 SPEC §6.2 删除。**替代方案见 ADR-019**：预算闸门改为「帮客户盯自己的钱」（厂商 usage 数据 + LiteLLM 单价，量级估算），超预算行为从 402 阻断改为警告 + 三态选项。
> 以下原文保留作历史留痕，**禁止按此实现**。

**落点：任务调度器（Hatchet worker 任务入口），不是网关、不是图内部。**

理由：网关做不了预占——它不知道预估成本（那是 Planner 在图内部算的）。图内部校验只能作为第三道防线（防长任务跑超）。

**三道校验各管一段**：

| 层 | 检查 | 阻断 | 写库 |
|----|------|------|------|
| API 网关 | 余额 > 0 | 快速 402 | 否 |
| **调度器（权威）** | `balance - reserved >= estimated` | 402 | **是（写预占）** |
| 图节点循环 | 累计/预估 > 80% | 预警 | 否 |
| 图节点循环 | 累计 >= 预估 × 1.5 | 熔断 | 否 |

**防超卖：预占-确认-释放两阶段账本 + PostgreSQL 行锁**（ADR-012 详述）

```
可支出 = balance - reserved
```

超卖的本质是 read-then-write 竞态：N 个并发任务同时读到同一 `remaining`，各自校验通过后同时扣费。**唯一的解法是把「校验+预占」变成一个数据库事务**，用 `SELECT ... FOR UPDATE` 串行化。

**三条关键设计**：

1. **权威账务必须在 PostgreSQL**，不能用 Redis 计数器（Redis AOF 每秒刷盘，宕机丢一秒账务）。Redis 只做快速失败
2. **settle 按实际扣不按预占扣**：预占是上界，实际通常更低，差额自动退回。不多扣客户钱
3. **预占带 `expires_at`，超时自动释放**：防进程崩溃后额度被「幽灵任务」永久冻结

**明确不做**：不引入 Redis 分布式锁做预占。PostgreSQL 行锁是唯一权威，引入 Redis 锁只会增加复杂度且正确性弱于 DB 行锁。

**账本 append-only**：`credit_ledger` 必须 `REVOKE UPDATE, DELETE`，与审计日志同等级别。账务流水可篡改 = 账务系统不可信。

### 14.3 平台代付风控 —— **[已作废 2026-10-15]**

> **作废原因**：同 §14.2，纯 BYOK 后平台零资金风险，本节讨论的赠送额度亏损/垫资风险/风控前置条件全部失去前提。以下原文保留作历史留痕，**禁止按此实现**。

**结论：PM 的立场（代付仅限少量试用用户、不做垫资）方向正确，但表述需要精确化。**

**关键区分**：

- **「不垫资」不等于「不亏损」**。平台仍然承担：赠送额度（纯成本）+ 免费用户滥用 + 模型厂商单价上涨 + 汇率波动 + 坏账（用户充值后跑长任务耗尽余额）
- 预付费模式能消除「余额透支」风险，但不能消除「赠送额度被滥用」风险——赠送额度是平台真金白银

**三个必须写进 PRD 的前置条件**：

| # | 条件 | 理由 |
|---|------|------|
| 1 | **赠送额度的熔断阈值必须比付费用户更严** | 平台垫钱的场景下，无进展检测的 N 值要收紧、预算上限要更硬 |
| 2 | **新用户赠送额度必须与首笔充值绑定**（充值 ¥X 送 ¥Y，Y ≤ X） | 杜绝「注册即领大额赠送→跑长任务→流失」的资金损耗 |
| 3 | **赠送额度设总量预算池，按租户分配且可过期** | 平台需要知道最坏情况下总成本上界（`Σ 所有未过期赠送额度`） |

**技术落地**：条件 1 走 ADR-011 的岗位级阈值（代付租户的 `expected_idle_steps` 默认调小）+ ADR-012 的预占闸门；条件 2/3 走 `credit_accounts` 的 `gift_expires_at` 字段 + 清理任务。

**结论**：风控站得住，但**必须在 PRD 里把「平台最大成本上界」显式写出来**（例如「赠送额度池总上限 ¥5,000，超出即停止新用户赠送」）。没有这个上界，风控就只是一个态度，不是一个控制。

### 14.4 模型能力前置校验：数据库标签表 + API 探测双层

**结论：双层。数据库能力标签表（权威）+ 厂商 API 探测（补充）。**

| 层 | 来源 | 优先级 |
|----|------|-------|
| L1 | `model_capabilities` 表（人工标注/探测结果落库） | 最高 |
| L2 | 厂商 API 运行时探测（缓存 24h） | 补充 |
| L3 | 保守默认（假设不支持） | 兜底 |

**关键设计**：
- **能力表在数据库而非代码常量** → 新模型上市运营加一行即可，**不发版**
- **fail-closed**：探测失败/超时一律判为不支持。这直接对应 PRD「不允许跑到一半失败」
- **节点粒度校验，不做岗位级整体校验**：单任务可能只需 `tool_use` 不需 `vision`，岗位级过严会阻塞合法任务
- **降级必须校验能力**：厂商故障切换备用模型前，**若备用模型能力不足则中止而非静默降级**。宁可不降级

**五个能力维度**：`vision` / `tool_use` / `long_context` / `json_schema` / `streaming`

**F1 需补的第二条**：岗位模板要声明 `required_caps` / `optional_caps`。

### 14.5 形态：MVP 不做 Tauri（确认 PM 判断）

**确认 PM 立场成立。本地能力不是 F6 的硬依赖。**

理由：
- F6 的四个要求（分步持久化/断点续跑/无进展检测/预估）**全部是服务端能力**，沙箱在服务端 gVisor，不依赖用户本地
- 知识源上传（PRD F5）是服务端处理，不是读用户本地文件
- 企微推送 + 响应式 Web 已覆盖「手机上看汇报」场景

**唯一需要 Tauri 的场景是「访问用户本地文件/本地模型」**，MVP 两者都不需要。Phase 2 若做本地模型能力再评估。

### 14.6 埋点自建：确认接受，并给技术约束

**确认 PM 的决策可接受，且这与我的可观测性边界设计（§9.6）一致。**

PRD 的理由（第三方 SDK 会让「不采集 IP、不存储原始输入内容」的承诺在技术层面被打脸）**技术上完全成立**——第三方 SDK 会自动采集 UA/IP/Referer 并上报到外部端点，这在技术上无法证伪我们的承诺。

**三条技术约束**：

1. **`trackEvent()` 必须自建，且必须在后端过滤后才入库**。不能只在前端不采集——前端代码可能被绕过。后端 `analytics_events` 表只接受白名单事件名与白名单属性
2. **事件表必须走RLS**（ADR-003），且**保留期有限**（建议 180 天），到期自动删除
3. **禁止记录的字段**：IP、User-Agent、原始输入内容、文件名、文件内容。这与 §9.6 可观测性边界一致

**指标口径建议**（PRD §8.4 的 7 条 Go/No-Go 判据需要能算出来）：

| 指标 | 口径定义 | 可行性 |
|------|---------|--------|
| TCR（任务完成率） | `task_completed` / (`task_completed` + `task_failed`) | 可算 |
| HITL（人机协作率） | `task_escalated_to_human` / `task_completed` | 可算 |
| 熔断率 | `task_circuit_broken` / 总任务数 | 可算 |
| 预算触发率 | `budget_warning_triggered` / 总任务数 | 可算 |
| 断点续跑成功率 | `task_resumed_from_checkpoint` 后续跑完成 / 中断次数 | 可算 |

**缺口提醒**：PRD §11.3 的事件清单里**没有「预估费用」的埋点**，但 §8.4 需要算「预估 vs 实际」的成本准确度。建议补 `cost_estimate_vs_actual_recorded` 事件，或直接从 `usage_records` 表算（后者更好，无需埋点）。

---

## 附录 A：版本验证记录

所有版本号于 2026-10-14 从官方 registry 实测拉取：

| 来源 | 验证方式 |
|------|---------|
| PyPI | `curl https://pypi.org/pypi/{pkg}/json` → `info.version` |
| npm | `curl https://registry.npmjs.org/{pkg}/latest` → `version` |
| pgvector | GitHub Tags API → `v0.8.7`（2026-10-01） |
| Next.js | nextjs.org/blog → 16.4（2026-10-06） |
| PostgreSQL | 假设 18.x（async I/O 为 18 特性，pgvector 0.8.7 兼容） |

**TypeScript 特别说明**：npm `latest` 为 7.0.2（原生重写版）。**锁定 5.9.x**，理由：TS 7 为 Go 原生重写，虽然性能大幅提升但生态兼容性（尤其 Next.js 16 的类型生成、Zod、ESLint 插件链）未充分验证。Phase 2 待生态稳定后再评估。

## 附录 B：关键实测数据来源

| 数据 | 来源 |
|------|------|
| RLS 性能（0-5% 开销；PL/pgSQL VOLATILE 170x 灾难） | PostgreSQL 17.10 实测，200 万行 / 1000 租户 |
| pgvector HNSW（recall@10 0.951 @ 1.15ms；索引 7.6GB/百万向量） | PostgreSQL 18.6 + pgvector 0.8.6/0.8.7 实测，99,000 条真实 embedding |
| pgvector 过滤不足行（iterative_scan 修复前后） | PostgreSQL 18.6 + pgvector 0.8.7，10 万条 384 维 |
| Firecracker 冷启动 ~125ms / < 5MiB | AWS Firecracker 官方文档 |
| gVisor I/O 开销 10-30% / syscall 覆盖 ~60% | 多来源交叉验证 |
| 沙箱成本（2000h/月省 66%，交叉点 1500-2500h） | 多来源交叉验证 |
| Hatchet 自托管 $30-80/月 | 2026-07 价格核实 |
| Hatchet Cloud 入门涨至 $500/月 | 2026-07 重新定价 |
| Next.js 安全节奏（月度安全发布） | nextjs.org/blog |
| SSE vs WebSocket 代理兼容差异 | 多来源交叉验证 |

---

## 15. 指标口径定义（回应对齐会议议题 5）

> 完整论证见 [ADR-015](decisions/ADR-015-metric-definitions.md)。PM 在 §8.4 给出 7 条判据与阈值，此处给出可计算口径。

### 15.1 七条判据的数据来源

| # | 判据 | 阈值 | 分子 | 分母 | 数据来源 |
|---|------|------|------|------|---------|
| 1 | TCR | ≥85% | `task_completed` 数 | `task_completed` + `task_failed` | `task_steps` + 埋点 |
| 2 | HITL | ≤2% | `task_escalated_to_human` 数 | 同上分母 | 埋点 |
| 3 | ROI | ≥300% | (节省人力 - 订阅费) | 订阅费 | `usage_records` + 人工折算参数 |
| 4 | 新用户首次跑完转化 | ≥40% | 7 日内 `first_run_completed` 用户 | 注册用户 | 埋点 |
| 5 | 注册到首次跑完中位时长 | ≤15min | 事件时间戳差 | — | 埋点 |
| 6 | 7 日留存 | ≥40% | 首跑后 7 日内 `session_start` 用户 | 首跑用户 | 埋点 |
| 7 | 成本不可预期投诉占比 | 0 | `tag=cost_unpredictable` 工单 | 全部退款工单 | 工单系统 |

### 15.2 三处定义歧义必须钉死

**歧义 1：TCR 与 HITL 的关系（影响判据 1、2）**

PRD 原文「任务完成率（无需人工介入完成）」有歧义。**采用：TCR 分子 = 完成且全程未经人工介入**。

理由：若「软阈值拉人确认后完成」也算 TCR 分子，则它同时被算进 TCR 分子与 HITL 分子，两条判据失去独立性，**HITL≤2% 就失去了约束力**。

| 事件 | 进 TCR 分子? | 计 HITL? | 计失败? |
|------|------------|----------|---------|
| 自主完成 | 是 | 否 | 否 |
| **软阈值拉人后完成** | **否** | **是** | 否 |
| 硬熔断（保留前序成果） | 否 | 否 | **是** |
| 不可恢复失败 | 否 | 否 | 是 |

满足恒等式：`TCR + HITL + 失败率 = 100%`（无重复计算）。

**熔断必须计失败** —— 这是最容易搞错的口径。熔断是保护机制不是成功，即使保留了前序步骤。**若把熔断算成功，熔断率会伪装成成功率。**

**歧义 2：ROI 的「节省人力」如何量化**

这是 7 条判据里唯一无客观数据来源的一条。**采用可配置参数法**：

```
节省人力 = Σ( task_templates.baseline_minutes_per_run × tenants.human_hourly_rate_cny / 60 )
```

**两个参数都必须是数据不是代码常量，且租户可配**。客户可把「兼职月薪 6000」换成自己的真实数字，ROI 随之变化。

意义：**ROI 是客户自己算的账，不是我们单方面的承诺**。销售用默认口径报价，交付后用客户口径复核。这同时降低了法律风险。

**歧义 3：「成本不可预期投诉」无采集路径**

PRD 要求占比 0，但当前**没有任何采集机制**。若客服不主动打标，这个数永远是 0（假通过）。

**必须改产品流程**：
- 退款/投诉原因改为**结构化枚举**，含「成本不可预期」固定选项
- 该字段**客服不可编辑**（只允许选择）
- 进 BI 看板与退款事件关联

**这是 7 条判据里唯一「必须改流程」才能满足的**，PM 需在 F8 或客服 SOP 落地。

### 15.3 判据需按岗位分组

ADR-014 已论证：竞品监控依赖第三方站点，**TCR 天花板天然低于其他岗位**。

| 岗位组 | TCR 阈值 | 理由 |
|--------|---------|------|
| 内部文档/表格类（周报汇总、发票核对） | ≥85% | 完全可控 |
| **外部依赖类（竞品监控）** | **≥70%** | 目标站改版/加防护会失败，行业常态 |
| 外部系统写入类（订单录入、催办） | ≥85% | 结果可验证 |

**聚合规则建议**：**每组单独判定，任一组不达标即整体 No-Go**（不做加权平均，避免用一岗的成功掩盖另一岗的失败）。

### 15.4 观测窗口

**判据 1/2 必须在 ≥2 周窗口上计算**，不看首日。外部依赖类任务的失败率随时间波动（目标站改版、促销期），首日数据不具代表性。

## 16. 对齐会议议题的架构侧结论

| 议题 | 架构侧结论 |
|------|-----------|
| 1. 排期压缩砍哪些 | 原则确认（砍功能不砍治理层与安全）。PM 补充的竞品论据（竞品差评 + 定价支撑）与我的判断一致。**架构侧无额外约束** |
| 2. 浏览器控制模块范围 | **已闭环**：三级能力分级，MVP 只做 L1。**L1 恢复第三方公开网页抓取**（用户复看裁定，推翻 C1 收窄），竞品监控日报为 MVP 岗位 #1。L2 不做；L3 不做自动登录，客户导出上传 |
| 3. 沙箱 POC 时间点 | **建议 Phase 2 第一周就跑，先于业务编码**。理由：gVisor 若不兼容，沙箱执行层需换 Kata Containers，越晚发现返工越大。且 POC 只需 2-3 天 |
| 4. 岗位卡片墙与难度递进 | 架构侧无约束。技术侧仅需保证 `job_template_id` 埋点可下钻（已列入 ADR-010约束） |
| 5. 判据指标口径 | **已闭环**：见 §15 与 ADR-015。发现 3 处歧义 + 1 处无采集路径（判据 7 需改客服流程） |

---

## 17. 中止态与事件可见性（Phase 1.5 补充）

> 完整论证见 [ADR-017](decisions/ADR-017-abort-state-and-visibility.md)。来源：设计师 UIUX §7.5.1/§7.5.2 + PM 接口层约束。

### 17.1 `stopping` 是独立状态，不是 flag

```
queued → running → stopping → cancelled
       └────────────→ completed  （中止生效前恰好跑完）
```

**后端硬约束**：

| 项 | 要求 |
|----|------|
| 状态枚举 | `goal_status` 含 `stopping`（**独立状态，不是 `is_cancelling` 布尔标志**） |
| **cancel 幂等** | **重复调用返回同一状态不报错**。UI 的 disabled 按钮是最后防线但**不能是唯一防线**（用户可能开两个标签页、或网络重试） |
| 实现顺序 | **先置 `stopping` 再发取消信号**（顺序不可颠倒）。否则用户点中止到看到反馈有 1-3 秒延迟，UI 无法显示中间态，用户会以为按钮坏了重复点 |
| 超时兜底 | `stopping` 最长 **5 秒**，超时由巡检器强制收敛为 `cancelled`。**保证 UI 永不卡在中间态** |
| 已完成步骤 | 保持原样，不回滚不置灰，**且不扣费** |
| 边界三种 | 恰好完成→直接 `completed` 不闪 `stopping`；`queued` 态中止→零延迟 `cancelled`；已 `cancelled`→幂等返回 |

### 17.2 事件可见性分级：`visibility` 字段，默认 admin

分界线是「**这件事老板需不需要知道？**」

| 级别 | 内容 | UI 呈现 |
|------|------|---------|
| L1 主叙事（owner 可见） | `task_started`/`step_completed`/`task_completed`/`task_failed`/`needs_human_input` | 时间轴一行摘要 |
| L2 细节（owner 可见，折叠） | `tool_called`/`retrieval_hit`/`file_written` | 折叠节点 |
| **L3 审计（仅 admin）** | `raw_prompt`/`raw_completion`/`retry_attempt`/`token_usage` | **owner 界面绝不出现** |

```sql
ALTER TABLE goal_events ADD COLUMN visibility TEXT NOT NULL DEFAULT 'admin';
```

**默认值方向是核心设计**：新增事件忘记标 `owner` 时**默认落 admin（安全）**，而非默认泄漏给老板。SSE 端点按调用方角色在**服务端**过滤。

**L1 禁止项**：不得含 `[INFO]`/`elapsed=`/token 数（对齐设计侧「禁止系统日志语汇」）。

### 17.3 用量接口：两个独立 endpoint

```
GET /api/v1/usage/summary    → OwnerUsageSchema  { task_count, cost_cents, breakdown_by_job }
                                                  （无 token / 无 model / 无 duration）
GET /api/v1/settings/usage   → AdminUsageSchema  { ..., input_tokens, output_tokens, model, ... }
```

**为什么不用同一 endpoint 按角色 oneOf**（回答 PM 的最后一问）：PM 定的原则是「承诺的不只是不记录，而是连返回给老板的接口里都不出现」。**若两视图共用一个 endpoint，token 字段就在 owner 的响应 schema 里**，只是被 controller 剔除——这与「schema 里不存在」不是一个强度。用两个 endpoint，**契约层本身就杜绝泄漏**，前端 `openapi-typescript` 生成的类型天然分离，owner 组件访问 token 直接编译报错。

**落库侧配套**：owner 口径数据来自 `tasks` + `cost_ledger` 聚合，**不读 `usage_records` 的 token 字段**——从数据源上断开，不是「读了再剔除」。

**PM 提的「省一次请求」不成立**：老板页与管理员页本就是两个独立页面，各自只需一个 endpoint，不产生额外请求。

### 17.4 埋点拆分

`report_viewed` → `owner_report_viewed` / `admin_usage_viewed`。不拆无法衡量老板是否真在用汇报页（PRD §8.4 留存判据依赖它）。

### 17.5 重要修正：AC-17 的引用依据已被证伪

PM 在 AC-17（误杀测试阻断级）中引用了我的原话「F6-lite 的 S1 是确定性零误判」作为理由。**该引用必须撤回**——ADR-016 已证明它错误：签名仅含工具名时，「下载 50 个竞品页面」在第 5 步即被误杀。

**AC-17 的结论正确但理由要改**：

| 项 | 内容 |
|----|------|
| 错误理由 | 「S1 零误判，所以测了个设计上不会失败的东西」 |
| **正确理由** | S1 收窄后**仍有非零误判率**（误杀条件收窄到「工具名+参数完全一致重复 5 次」，但非数学证明为零）；**且 S2 是 F6-lite 新增信号，阈值需实测调参** |

**且 AC-17 必须补一条**：误杀测试需验证**修正前后的行为差异**——用仅含 `tool_name` 的旧签名跑「下载 50 页面」应误杀，新签名应放行。**否则测试无区分力，测了也白测。**

**这条必须在 Phase 2 前改**，否则会误导开发者认为 S1 天然无误杀风险而不正确实现参数签名。

| 议题 | 架构侧结论 |
|------|-----------|
| 1. 排期压缩砍哪些 | 原则确认（砍功能不砍治理层与安全）。PM 补充的竞品论据（竞品差评 + 定价支撑）与我的判断一致。**架构侧无额外约束** |
| 2. 浏览器控制模块范围 | **已闭环**：三级能力分级，MVP 只做 L1。**L1 恢复第三方公开网页抓取**（用户复看裁定，推翻 C1 收窄），竞品监控日报为 MVP 岗位 #1。L2 不做；L3 不做自动登录，客户导出上传 |
| 3. 沙箱 POC 时间点 | **建议 Phase 2 第一周就跑，先于业务编码**。理由：若 gVisor 不兼容，沙箱执行层需换方案，越晚发现返工越大。且 POC 只需 2-3 天 |
| 4. 岗位卡片墙与难度递进 | 架构侧无约束。技术侧仅需保证 `job_template_id` 埋点可下钻（已列入 ADR-010约束） |
| 5. 判据指标口径 | **已闭环**：见 §15 与 ADR-015。发现 3 处歧义 + 1 处无采集路径（判据 7 需改客服流程） |
---

## 18. 熔断语义分离与 F8 取舍（Phase 1.5 第三轮补充）

> 完整论证见 [ADR-018](decisions/ADR-018-circuit-break-semantics.md)。本轮两项是修正我自己的建议。

### 18.1 F8 取舍排序：我采纳 PM 的反驳

我上一轮建议「先砍 F8 或减少岗位数量」。**PM 反驳并给出我没想到的论证，我采纳她的排序。**

**PM 的论证**：老板汇报打开率是最重要的留存指标，砍掉 F8 后老板必须主动打开网页，**直接影响判据 6「7 日留存 ≥40%」与激活定义**。砍岗位数量只减少覆盖面，不影响任何判据。

**我复核 PRD 后确认她是对的**：

| 判据 | 是否依赖 F8 | 依据 |
|------|------------|------|
| 判据 6「7 日留存」 | **是** | 留存事件 `session_start`/`owner_report_viewed`/`daily_report_clicked`，**推送是这些事件的触发器** |
| 激活定义 | **是** | 激活含 `first_report_viewed` + `daily_report_clicked` |
| TCR / HITL / ROI | 否 | 与推送无关 |

**我原排序错在**：只看了「F8 是渠道不是能力」，**忽略了渠道决定了判据 6 的事件能否发生**。这是工程视角与产品视角的差异。

**修正后排序**（依据「砍掉会让哪条判据失效」）：

```
1. 岗位数量（5 → 3）    代价：覆盖面        不影响任何判据
2. F8（企微推送）       代价：判据 6 + 激活定义
3. F6（最后才考虑）     代价：TCR 判据本身失效
```

**方法论教训**：取舍排序不应由架构单方决定。架构侧评估「实现成本与判据影响」时容易漏掉「事件触发器」这一层。

### 18.2 熔断与员工判断必须语义分离

| 语义 | 图标 | 位置 | 文案示例 |
|------|------|------|---------|
| 员工主动判断不确定 | `Hand` | 汇报页③ + 员工卡片 + **待确认队列** | 「我没敢填客户等级」 |
| 系统熔断 | `CircleDashed` + `CircleAlert` | **任务行内联（不占队列名额）** | 「这一趟卡住了，我停下来等你」 |

**为什么熔断不占队列名额**：队列是给「需要老板做决定」用的。熔断时系统已停止并保留成果，**不需要老板做任何决定**，塞进队列会稀释队列信号强度并造成疲劳。

**架构落点**：`needs_human_input`（进队列）与 `circuit_break`（任务行内联）是两类不同事件，禁止合并。

**降频规则**：降频三级只作用于 `needs_human_input`；**`circuit_break` 不受降频影响，每次必须可见**（隐藏它等于隐藏系统缺陷）。

### 18.3 熔断文案禁止暴露系统行为

**若界面暴露「我们收紧了限制」，老板会理解为「之前那些产出可能是靠运气」**——这会一次性摧毁「我停下来问过 N 次，它们没有一次是猜的」的可信度。

| 禁止 | 允许 |
|------|------|
| 「由于无进展检测阈值调整为…」 | 「我在检索这一步卡住了，因为需要你授权店铺后台」 |
| 「触发熔断（连续 5 步无进展）」 | 「我在这一步停下来了，前面 7 步的成果都留着」 |

**技术侧配合**：`error_code` 保留在数据库与审计日志（供排查），但**不进入 owner 可见文案**。与 §17.2 的 `visibility` 分级同一思路。

### 18.4 F6-lite 事件类型清单（19 个）

owner 可见 10 个，admin-only 9 个。**完整表格见 ADR-018 §5。** 关键约束：

- **L1 禁含** `[INFO]`/`elapsed=`/token 数
- **未列入清单的新事件默认落 `visibility='admin'`**（ADR-017 §17.2 的默认值方向）
- 已实包验证全部 18 个图标在 `lucide-react@1.57.0` 中存在

### 18.5 图标门禁扩展为双向

设计师指出我的脚本只管新增不管删除——**删掉一个状态后某处旧 import 会静默变 undefined 而不报错**。已 Node 实测确认（解构缺失键得 `undefined`，静默无报错；ESM 具名导入通常构建时报错，但 re-export / map 引用场景会静默渲染空白）。

| 方向 | 检查 |
|------|------|
| 新增 | 源码中所有 `from 'lucide-react'` 导入名必须存在于包导出 |
| **删除** | 包中已移除的导出名若仍被源码引用则**阻断**（对照历史 lock 导出快照） |

---

## 19. 纯 BYOK 修订：成本可见性替代平台计费（Phase 1.5 第四轮）

> 完整论证见 [ADR-019](decisions/ADR-019-pure-byok-cost-visibility.md)。产品方向变更：删除平台代付。

### 19.1 ADR-012 部分作废

| ADR-012 原内容 | 裁定 |
|---------------|------|
| 预占-确认-释放两阶段账本 + PG 行锁 | **作废**（平台不经手资金） |
| `credit_ledger` append-only | **作废**（平台无计费流水） |
| 赠送额度池上界 | **作废** |
| 代付租户熔断阈值更严 | **作废** |
| **权威数据在 PG 不用 Redis 计数器** | **保留，对象改为成本归集** |
| **事件幂等** | **保留，且优先级升级**（见§19.3） |

### 19.2 成本预估在纯 BYOK 下成立，但精度有限

**成本数据源从来不是平台账本，而是厂商返回的 `usage`**——这与谁付钱无关：

```
成本 = Σ(input_tokens × 单价_in + output_tokens × 单价_out)
```

**单价来源**：厂商**无价格 API**，价格只在文档网页。采用 **LiteLLM `model_prices_and_context_window.json`**（行业事实标准，3850+ 模型，社区每日同步），每日同步 + 本地快照兜底（拉取失败回退快照，不中断服务）。

**三个已知精度限制（必须写进 UI，不得假装精确）**：

| 限制 | 幅度 | 处理 |
|------|------|------|
| 峰谷定价 | DeepSeek 峰时段单价翻倍 | 标注「按非峰时段估算」 |
| 缓存命中差异 | DeepSeek 缓存命中 ¥0.02 vs 未命中 ¥1，**差 50 倍** | 按部分命中加权，**给区间不给单值** |
| 长上下文阶梯 | Gemini/Grok/GPT-5 超阈值涨价 | 标注「不含阶梯加价」 |

**结论：预算是「量级估算」不是「精确报价」。** 用于判断是否超预算合理；**禁止用于「这个任务确切要花 ¥3.42」这类表述**。

### 19.3 预算闸门保留，但性质改变

| 维度 | 代付时代 | 纯 BYOK |
|------|----------|---------|
| 闸门目的 | 平台止损 | **帮客户盯自己的钱** |
| 超预算行为 | **阻断**（402） | **警告 + 告知后果**，不硬拦 |
| 超预算必要性 | 必须（平台要止损） | 仍然必要（高频定时任务 + 无预算 = 客户账单烧穿） |

**纯 BYOK 下不能沿用「超预算硬拦」——客户花自己的钱，我们无权替他决定不能花。**

**幂等约束优先级升级**：代付时代重复记账坑平台的钱；纯 BYOK 时代重复记账坑的是**客户对平台的信任**（他看到自己账单虚高 3 倍会立刻失去信任）。

### 19.4 表结构变更

| 表 | 处置 |
|----|------|
| `credit_accounts` / `credit_reservations` / `credit_ledger` | **删除** |
| `usage_events` / `usage_records` / `agent_budgets` | **保留** |
| `model_pricing` | **新增**（LiteLLM 价格表落地，版本化） |

### 19.5 账套号：已实现，零改动

`tenant_code`（`AC-` + 8 位 Base32）在 ADR-003 账套号体系中已实现，**恰好匹配线下收款开户需求**：

- **可口述可截图**——线下付款时报「账套号 AC-8F3K2M9W」
- **不可枚举**——8 位 Base32 = 40 bit
- **不用统一社会信用代码**——那是企业注册号不是账套号，且一企业可能开多账套
- **一客户多账套天然支持**（一租户一 `tenant_id`）

**唯一建议**：`tenant_code` 在 UI 提升显眼度（账套设置页顶部大字 + 复制按钮 + 线下付款说明）——它现在是线下收款的唯一凭据。

### 19.6 隐私承诺恢复为绝对

删代付后设备指纹采集需求消失，**「不采集 IP」恢复为一条无例外的绝对承诺**。三条约束（§9.6 数据边界 / AC-14b 接口层不返回 / owner·admin 双endpoint）现在完全自洽，**无任何例外分支**。这消除了「销售拿『我们不采集 IP』回答质询」的法律风险。
