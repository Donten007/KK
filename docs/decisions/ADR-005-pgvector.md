# ADR-005: 向量能力采用 PostgreSQL + pgvector，不引入独立向量数据库

## Status
Accepted (2026-10-14)

## Background

产品有 3 个功能需要向量检索：

1. **知识库**（RAG）—— 客户上传文档，Agent 检索相关片段
2. **记忆系统** —— 长期记忆的语义召回
3. **资产中心** —— 相似资产检索（可选）

同时这3 处都必须叠加 `tenant_id` 过滤——**这是 RLS 最容易被绕过的地方**（见 Consequences）。

选型核心权衡：引入独立向量数据库（Qdrant/Milvus/Weaviate/Pinecone）能拿到更好的检索性能，但会新增一个需要运维的有状态服务、新增一套备份、新增一份跨库一致性问题，且**多租户过滤要在向量库里重做一遍安全机制**。

## Decision

采用 **PostgreSQL 18 + pgvector 0.8.7**，向量与业务数据同库同实例。

**关键决策点**：

- 向量列类型：`vector(1536)`（OpenAI text-embedding-3-small 默认维度）
- 索引类型：**HNSW**（`m=16, ef_construction=64`），查询时 `ef_search=80`
- 距离算子：`vector_cosine_ops`
- **必须启用 `hnsw.iterative_scan = relaxed_order`**（pgvector 0.8.0 引入，详见下方"已内嵌的坑"）
- 未来存储吃紧时降级路径：`halfvec(1536)`（存储减半，召回损失极小）

## Alternatives Considered

### 方案 A：PostgreSQL + pgvector（选中）

**评分：4.5 / 5**

| 维度 | 权重 | 评分 | 依据 |
|------|------|------|------|
| 运维成本 | 高 | 5 | 零新增组件。备份、监控、迁移、高可用全部复用 |
| 事务一致性 | 高 | 5 | 向量与元数据在同一事务里。删文档 = 删向量，不存在"删了元数据向量还在" |
| 多租户过滤 | 高 | 5 | **同一套 RLS 策略直接生效**。独立向量库要重做一遍隔离机制，且极易漏 |
| 检索性能 | 高 | 4 | 足够（见实测数据） |
| 规模上限 | 中 | 3 | 见下方"何时该outgrow" |
| 检索特性 | 中 | 3 | 不支持混合检索（BM25 + 向量）的原生融合，需应用层实现 |

**实测性能**（PostgreSQL 18.6 + pgvector 0.8.7，99,000 条真实 embedding，1536 维）：

| 检索方式 | Recall@10 | P50 延迟 | 索引大小 |
|---------|----------|---------|---------|
| 精确检索（无索引） | 1.000 | 158.9 ms | — |
| HNSW（默认参数） | 0.951 | 1.15 ms | 773 MB（≈7.6 GB/百万向量） |
| HNSW（ef_search=100） | 1.000 | 1.75 ms | 同上 |

即：**1.15ms 拿到 95% 召回，比精确检索快 138 倍**。对 RAG 场景（HNSW Top-50 + 重排 + 权限过滤 → Top-5）完全够用。

另有一组更严苛的实测（100,000 条 384 维，PG 18.6 + pgvector 0.8.7）：

| 配置 | Recall@10 | P50 | P95 |
|------|----------|-----|-----|
| 精确，无索引 | 1.000 | 26.98 ms | 30.48 ms |
| HNSW ef_search=10 | 0.924 | 0.46 ms | 0.76 ms |
| HNSW ef_search=40（默认） | 0.990 | 0.73 ms | 1.27 ms |
| HNSW ef_search=100 | 1.000 | 1.75 ms | 2.37 ms |

结论：`ef_search=80~100` 可把召回做到 1.000，延迟仍 < 2.4ms。

### 方案 B：Qdrant

**评分：3 / 5**

| 维度 | 权重 | 评分 |
|------|------|------|
| 检索性能 | 高 | 5 —— payload 过滤 + 量化更成熟，大规模下优势明显 |
| 运维成本 | 高 | 2 —— 新增有状态服务 |
| 多租户过滤 | 高 | 3 —— payload filter 可做，但 RLS 机制要重做一遍 |
| 运维复杂度 | 高 | 2 —— 曾出现"仅需网络访问 port 9091"的多起 CVE |
| 生态 | 中 | 4 |

实测对比（同机 8vCPU/15.6GiB，同一份 10 万条 384 维数据）：pgvector HNSW（ef_search=40）P50 0.73ms / P95 1.27ms / recall 0.990。Qdrant 在此规模同量级。

否决理由：**在 10 万到 100 万向量规模内，两者性能没有可观测差异**。为一个用不到的规模优势付出运维成本和多租户安全重建的成本，不划算。Qdrant 保留为"outgrow pgvector"的首选迁移目标。

### 方案 C：Milvus

**评分：2 / 5**

运维成本最高（需etcd + MinIO + Milvus 三组件）。检索性能上限最高。规模优势要到千万级以上才显现。中文场景无分词优势。否决。

### 方案 D：Weaviate

**评分：2 / 5**

模块化设计好，但资源占用明显高于 pgvector（Qdrant/pgvector 对比结论："Milvus/Qdrant/pgvector 三者对比，pgvector 和 Qdrant 在中等规模下资源占用远低于 Weaviate"）。运维复杂度中等。否决。

### 方案 E：Pinecone（托管）

**评分：1.5 / 5**

省运维，但数据必须出境（违反中国大陆客户合规预期）、按量计费在 Agent 场景下不可预测、无法叠加本项目的 RLS、多租户过滤要在云端重做。**否决。**

## Consequences

### 正面

- **多租户隔离零成本**：向量表的 `tenant_id` 走 ADR-003 的同一套 RLS 策略，不存在"向量库忘了加tenant 过滤"这个漏洞
- **事务一致性**：文档入库 = 元数据 + 向量在同一事务，删文档不留孤儿向量
- **零新增运维组件**：备份/高可用/监控全部复用
- **PostgreSQL 18 的原生异步 I/O 白送收益**：当 HNSW 索引放不进内存时（1536 维百万级很常见），顺序扫描性能提升 30-40%，零配置零改代码

### 负面

**四条必须内嵌 Spec 的已知坑：**

1. **【最严重】过滤 + ANN 会返回不足 N 行**。HNSW 索引扫描后才应用 `WHERE`，条件的选择性高时（如 `WHERE category = 7` 只有 1% 行），实际拿到的行数**远少于**请求的 LIMIT。实测 `category=7`（989 行/10 万，约 1%）时：迭代扫描关闭 → 返回 **0.4 行**（期望 10 行）；`relaxed_order` → 返回 10 行但 recall 掉到 0.841；`strict_order` → recall 0.665。**解法：必须设 `hnsw.iterative_scan = relaxed_order`**（0.8.0 引入）。这是 pgvector 0.8 史上体验提升最大的一处改动

2. **不能在同一个索引里混用不同 embedding 模型的向量**。距离变得毫无意义，而且**不报错**。必须用单独索引或单独表，且在表注释/服务层强制标注 `embedding_model`

3. **索引体积是真成本**：float32 HNSW 索引 7.6 GB/百万向量（1536 维）。存储吃紧时的降级顺序是：`vector` → `halfvec`（约50% 更快的构建速度，召回损失极小）→ 二值量化（`bit`，构建快约 150 倍，但召回掉 5-10%，**必须用 full 向量对 top-100 重排**）

4. **HNSW 建索引慢于IVFFlat、占内存更多**。构建百万级索引必须显式设置：`SET maintenance_work_mem = '2GB'` + `SET max_parallel_maintenance_workers = 8`（0.8 的并行构建可让建索引时间降 30-50%）

**另一条多租户专属风险**：向量检索的 tenant 过滤有两种做法，**必须都做**：

- RLS 策略（数据库层，兜底，不可绕过）
- 查询里显式 `WHERE tenant_id = X`（应用层，让查询计划能选对索引，且让 RLS 在 EXPLAIN 里可见）

只做 RLS 不做显式 WHERE 的风险：查询计划可能选到不理想的计划。且排查问题时看不到过滤条件。只做显式 WHERE 不做 RLS 的风险：漏一处就是跨租户泄露。**两者都要**（ADR-003 已确立此原则，此处是它在向量检索的具体化）。

### 中性：何时该 outgrow pgvector

触发条件（满足任一即启动迁移评估）：

- 单表向量数 > 2000 万（7.6GB/百万 → 约 150 GB 索引，超单表合理规模）
- P95 检索延迟 > 50ms 且已确认非配置问题
- 需要混合检索（BM25 + 向量）的原生融合，且应用层实现成本已高于引入专用库

迁移首选目标：Qdrant（届时规模下它的量化与 payload 过滤优势才有实际意义）。迁移不影响业务语义，只影响检索层，故此项不阻塞MVP。

## Related ADRs

- ADR-003（多租户 RLS）—— 本 ADR 是其在向量检索场景的具体化
- ADR-001（Agent 内核）—— RAG 三层漏斗（向量 Top-50 → BM25 重排 → 权限过滤 → Top-5）在图节点中实现

## Verification

**存在性核验**：

```bash
psql -c "SELECT extversion FROM pg_extension WHERE extname='vector';"  # 应为 0.8.7
psql -c "SHOW hnsw.iterative_scan;"
```

**端到端验证步骤**：

1. 建 `kb_chunks` 表：`embedding vector(1536)`，插入 10 万条真实 embedding
2. 建 HNSW 索引：`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`
3. **过滤不足行数用例（阻断级，对应坑 1）**：
   - 数据分布：一个分类占约 1%（989/10 万）
   - `SET hnsw.iterative_scan = relaxed_order; SET hnsw.ef_search = 80;`
   - 执行 `SELECT ... WHERE category = 7 ORDER BY embedding <=> $1 LIMIT 10`
   - 断言：返回**恰好 10 行**（关闭 iterative_scan 时会返回 0-1 行）
4. **召回率断言**：同一人工标注集，断言 recall@10 >= 0.98
5. **多租户隔离断言（阻断级）**：
   - `SET LOCAL app.current_tenant='A'` → `SELECT ... WHERE category=7 LIMIT 10`（不加显式 tenant 条件）
   - 断言：返回 10 行，且全部属于 A
   - 显式传 `'B'` 作为 tenant 条件 → 断言返回 0 行
6. **索引体积监控**：断言 10 万条 1536 维的索引大小合理，记录基线；超 10 GB/百万向量即告警
7. **模型隔离**：建两张 embedding 模型的表，断言各自的 HNSW 索引独立存在（未混在同一索引）

第 3、5 条为阻断级。