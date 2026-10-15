# ADR-003: 多租户采用共享 Schema + tenant_id + PostgreSQL RLS 三层防护

## Status
Accepted (2026-10-14)

## Background

用户已确认决策 #2：**云端 SaaS 多租户**，不是桌面单机。这是与 EvoFlow 最本质的架构差异。

EvoFlow 是单机桌面应用，SQLite 单文件，无租户概念。我们要把它变成卖给多个中小企业老板的 SaaS，就必须从零建立多租户隔离。

**风险量化**：多租户系统最严重的故障模式是**跨租户数据泄露**。这不是"数据错了一点"，是"公司 A 的老板看到了公司 B 的老板的报价单"，一次就足以毁掉产品信誉和公司。因此租户隔离不是"性能优化项"，是**安全底线**，必须做成多层、且不依赖任何单一层的正确性。

MVP 阶段的现实约束：
- 客户是中小企业老板，租户数量在百级而非万级（自助注册增长后才会上升）
- 团队规模小，不可能有专人做 DBA 运维
- 但隔离强度不能因为租户少就打折——攻击者只需要成功一次

## Decision

采用**共享数据库 + 共享 Schema + `tenant_id` 列 + PostgreSQL Row Level Security**，配套**账套号体系**，并实施**三层强制防护**。

**核心组件**：

1. **账套号体系**：每个租户有唯一 `tenant_id`（UUID v4，内部主键）+ 人类可读的 `tenant_code`（如 `AC-8F3K2M`，对外暴露用，对应"账套号"）
2. **连接层防护**：每张租户表 `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)`
3. **查询层防护**：Repository 层强制显式 `tenant_id` 条件（不依赖 RLS 作为唯一防线，RLS 是兜底网）
4. **校验层防护**：越权自动化测试（pytest + pgTAP 双层）

**数据库**：PostgreSQL `18.x` + pgvector `0.8.7`

## Alternatives Considered

### 方案 A：共享 Schema + tenant_id + RLS（选中）

**评分：4.5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 隔离强度 | 高 | 4 | 数据库层强制，唯一无法被应用层漏写 WHERE 绕过的层 |
| 运维成本 | 高 | 5 | 一个数据库，一套备份，一套迁移 |
| 租户规模上限 | 中 | 4 | 单库可支撑数千租户、数亿行；RLS 开销可忽略 |
| 查询性能 | 高 | 5 | 正确索引下开销 0-5%（见下方实测数据） |
| 迁移复杂度 | 中 | 5 | 从零开始，无历史包袱 |
| 大租户隔离 | 中 | 2 | 无法给单个大客户单独拆库（但有迁移路径） |

**RLS 性能实测数据**（PostgreSQL 17.10，200 万行 invoices 表 / 1000 租户，索引 `(tenant_id, issued_on)`）：

| 查询模式 | 无 RLS | 有 RLS（简单比较式策略） | 开销 |
|---------|-------|----------------------|------|
| 最大租户 COUNT（26.7 万行） | 11.0 ms | 11.0 ms | 0% |
| 中位租户取最新 50 条 | 0.34 ms | 0.30 ms | 0%（噪声范围内） |
| 单行按主键 | 0.42 ms | 0.43 ms | +2.4% |
| 三表 JOIN | 8.4 ms | 8.9 ms | +5.9% |
| 100 万行聚合 | 35 ms | 36 ms | +3% |

结论：**RLS 在正确写法 + 正确索引下开销不可测量**。PostgreSQL 会把策略条件折叠进查询计划，等价于一个普通的 WHERE 子句。

**但有一个致命陷阱**：策略里取 tenant_id 的方式决定了性能是 0% 还是 1000 倍。实测：

| 策略写法 | 最大租户 COUNT | 结论 |
|---------|---------------|------|
| `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` | 11.0 ms | 正确写法，零开销 |
| SQL 函数（VOLATILE 或 STABLE 均可被内联） | 15.0 ms | 可接受 |
| **PL/pgSQL 函数（VOLATILE 默认）** | **1,877 ms** | **灾难：170 倍开销** |
| PL/pgSQL 函数（显式 STABLE） | 14.5 ms | 可接受 |
| `(SELECT plpgsql_volatile_func())` 包裹 | 14.6 ms | 可接受 |

原因：PL/pgSQL 函数**无法被内联**。声明为 VOLATILE（不声明时的默认值）时，它必须对每一行调用一次，索引失效，退化为对 200 万行的顺序扫描——连只有 534 行的中位租户也一样慢。

**这就是本 ADR 的关键约束**：策略里**只允许**用 `NULLIF(current_setting(...), '')::uuid` 这个内联式表达式，**禁止**用 PL/pgSQL 辅助函数。这是必须在代码评审和迁移模板里做成硬规则的一条。

### 方案 B：每租户独立 Schema

**评分：2.5 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 隔离强度 | 高 | 5 —— 彻底隔离，跨租户连查询语法都用不了 |
| 运维成本 | 高 | 1 —— N 个租户 = N 套 schema + N 份迁移，100 个租户时迁移脚本要跑 100 次 |
| 查询性能 | 高 | 3 —— 每租户独立缓存，冷启动慢 |
| 租户规模上限 | 中 | 3 —— 连接数、schema 数量、迁移时间都是硬墙 |
| 实施成本 | 中 | 2 —— Alembic 动态 schema 路由，复杂度陡增 |

否决理由：SQLAlchemy/Alembic 的迁移模型是"一套 schema 跑所有环境"，动态 schema 意味着每次迁移都要遍历所有租户 schema，在百级租户规模下这会让每次发版变成运维噩梦。隔离强度虽好，但 RLS 已经提供了数据库层的强制隔离，收益不足以抵消运维成本。

保留价值：作为**大客户升级路径**保留。架构文档中定义了从共享 Schema 升级到独立 Schema 的迁移流程，当某租户提出数据驻留/合规要求时单独升级。

### 方案 C：每租户独立数据库

**评分：2 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 隔离强度 | 高 | 5 —— 最强 |
| 运维成本 | 高 | 1 —— N 个数据库 = N 套备份/监控/升级/连接池 |
| 跨租户运营查询 | 中 | 1 —— "平台管理员看所有租户的用量"需要跨 N 个库做联邦查询 |
| 成本 | 高 | 2 —— 百租户时数据库实例费用进入五位数/月 |
| 实施成本 | 高 | 1 —— 连接路由、迁移编排、连接池管理全部重写 |

否决理由：这是金融/医疗/政企的方案，我们是中小企业 SaaS。百级租户时运维成本会压垮小团队。唯一不可替代的场景是"客户要求数据物理隔离且可审计"，但那属于 Scale 阶段的销售谈判筹码，不是 MVP 必需。

### 方案 D：应用层过滤（不用 RLS）

**评分：1.5 / 5**

只在每个 WHERE 子句里加 `tenant_id = ?`。

否决理由：**这正是要否决的方案**。它把隔离的正确性 100% 押在"每个开发者每次查询都记得加条件"上。漏一个 WHERE 就是跨租户泄露，而且不会有任何报错——测试照过、日志正常、只是返回了别人的数据。这是典型的沉默逻辑错误，最致命的一类失效模式。

RLS 的核心价值不是性能，是**它把隔离放在唯一无法被"漏写 WHERE"绕过的层**。应用层过滤保留，但降级为"查询计划可见性 + 纵深防御"，不再是唯一防线。

## Consequences

### 正面

- **隔离正确性由数据库保证**：即使应用代码有 bug、漏写 WHERE、甚至有人手动执行 SQL，RLS 仍然挡住跨租户访问
- **一套备份、一套迁移、一套监控**：运维成本最低
- **性能开销不可测量**：0-5%，在正确索引下
- **LangGraph checkpoint 表可复用同一套 RLS 机制**（放在独立 schema 但启用同样的策略）

### 负面

**四条必须在迁移模板和代码评审中固化的硬规则：**

1. **必须 `FORCE ROW LEVEL SECURITY`**。只写 `ENABLE` 的话，表 owner 依然能看到全部数据——不报错、不告警、owner 静默绕过全部策略。而表 owner 恰恰是应用最可能使用的连接身份
2. **策略里禁用 PL/pgSQL 函数**，只用 `NULLIF(current_setting('app.tenant_id', true), '')::uuid` 内联式。写成 PL/pgSQL 且未标 STABLE 会导致 170 倍性能退化，且中位租户同样受害（小租户不因为行数少就免灾）
3. **必须用 `SET LOCAL`（事务作用域），不能用 `SET`（会话作用域）**。会话作用域的设置会在连接池复用时泄漏给下一个请求的用户——这是一个不报错、只泄漏的隐蔽越权。PgBouncer transaction 模式下 `set_config` 的第三个参数必须传 `true`
4. **视图必须显式 `security_invoker = true`**（PG 15+）。视图默认以 owner 权限运行，会绕过 RLS

其他负面：

- **每张新表都要手工加策略**，漏加即失去隔离。必须在 Alembic 迁移模板里内建 RLS 启用逻辑，让"新建表"和"启用 RLS"在物理上无法分离——这是防止漏加的唯一可靠办法
- **`app.current_tenant` 未设置时策略返回 NULL，查询返回 0 行**（fail-closed）。这是正确行为，但会让"忘记设置租户上下文"的 bug 表现为"列表页空了"而非报错。必须在前端/后端日志中把这种情况显式告警
- **超级用户绕过 RLS**。应用连接串绝不能用 superuser，代码评审硬规则
- **RLS 与 ORM 预编译语句计划缓存可能掩盖过期上下文**。部分 ORM 缓存 prepared statement plan，理论上可能钉住旧的 tenant 设置。必须在测试环境开`log_min_messages = debug2` 验证不发生

### 中性

- 大租户（单租户行数超千万）时共享 Schema 会让 vacuum/索引维护变慢。触发阈值：单租户任一表超 1000 万行 → 评估升级到独立 Schema。百级租户规模下这个阈值不会触发

## Related ADRs

- ADR-001（Agent 内核）—— LangGraph 的 checkpointer 写入需带 tenant 上下文
- ADR-005（向量数据库）—— 向量检索必须叠加 `tenant_id` 过滤，这是 RLS 最容易被绕过的地方（见下）
- ADR-009（安全中心）—— 本 ADR 是安全中心的隔离层实现

## Verification

**存在性核验**：

```bash
psql --version   # PostgreSQL 18.x
psql -c "SELECT * FROM pg_available_extensions WHERE name='vector';"  # pgvector 0.8.7
```

**端到端验证步骤（越权测试套件，必须进 CI，不通过即阻断发布）**：

1. 造两个租户 A、B，各插入业务数据
2. **正向用例**：
   - `SET LOCAL app.current_tenant = 'A'` → A 能看到自己的数据
   - `SET LOCAL app.current_tenant = 'B'` → B 能看到自己的数据
3. **零上下文用例**：
   - `RESET app.current_tenant` → 查询返回 **0 行**（fail-closed），且日志中有显式告警
4. **跨租户越权用例（核心）**：
   - `SET LOCAL app.current_tenant = 'A'` → 显式 `SELECT * FROM projects WHERE tenant_id = 'B'::uuid` → 返回 **0 行**
   - 同上条件下 `INSERT INTO projects(tenant_id, ...) VALUES ('B', ...)` → 报 **RLS policy violation 错误**
   - 同上条件下 `UPDATE projects SET ... WHERE tenant_id = 'B'` → **0 行受影响**
   - 同上条件下 `DELETE FROM projects WHERE tenant_id='B'` → **0 行受影响**
5. **表 owner 绕过用例**：
   - 用 owner 身份连接（不 FORCE 时会绕过），断言 FORCE 已生效 → 跨租户查询仍返回 0 行
6. **连接池串味用例**：
   - 事务1 设置 `app.current_tenant='A'` 并提交
   - 不重置，直接在同一物理连接开启事务2
   - 断言：事务2 **查不到任何数据**（证明 `SET LOCAL` 生效，会话作用域未泄漏）
7. **视图绕过用例**：
   - 创建一个未加 `security_invoker` 的视图，跨租户查询该视图
   - 断言：**报错或返回 0 行**，不允许返回 B 的数据
8. **性能回归**：
   - 用 pgTAP 或 pytest-benchmark 跑最大租户 COUNT，断言 P95 < 20ms（RLS 开销 < 30%）
   - 断言 `EXPLAIN` 中 `tenant_id` 走的是 `Index Cond` 而非 `Seq Scan`

其中第 4、5、7 条是**阻断级**用例：任一失败即视为租户隔离不成立，禁止发布。