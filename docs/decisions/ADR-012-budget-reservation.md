# ADR-012: 预算三元组采用「预占-确认-释放」两阶段账本防止超卖

## Status
Accepted (2026-10-14)

## Background

PRD §10.2 定下三元组计费模型：**岗位编制数 + 执行次数 + 每编制月度预算上限**。

PRD 的硬要求（验收标准原文）：

> Given 用户代付余额仅剩 0.5 元但预估任务需 3 元，When 发起任务，Then 系统在执行前提示预估费用并要求确认，**不允许透支执行**

> Given 某 AI 员工本月预算 200 元已用 200 元，When 下一个定时任务到达，Then 任务**不执行**

PM 提出两个技术问题：

1. 预算校验落在哪一层（网关 / 中间件 / 任务调度器）？
2. **如何防止并发任务同时通过校验导致预算超支（超卖）？**

第二个问题是真正的难点。第一个问题看起来只是分层选择，但答案由第二个问题决定。

**超卖的本质**：预算是账户上的一个标量余额 `remaining`。校验逻辑是 `remaining >= estimated_cost`。若有 N 个并发任务同时读到同一个 `remaining`、各自校验通过、然后各自执行扣费，实际消耗可能远超 `remaining`。

```
时刻 t0: remaining = 100
时刻 t1: 任务 A 读remaining=100，预估 30 -> 通过
时刻 t1: 任务 B 读 remaining=100，预估 30 -> 通过（A 尚未写入）
时刻 t1: 任务 C 读 remaining=100，预估 90 -> 通过
时刻 t2: 三个任务同时扣费 -> 实际消耗 150 > remaining 100  -> 超卖 50
```

这是经典的 read-then-write 竞态。**关键约束：这是钱的账务，不允许最终一致，必须强一致。**

## Decision

**采用「预占（reserve）→ 确认（settle）→ 释放（release）」两阶段账本，落点在任务调度器层（Hatchet worker 的任务入口），Redis 分布式锁 + PostgreSQL 事务双保险。**

**余额账本三张表**：

| 表 | 作用 | 关键字段 |
|----|------|---------|
| `credit_ledger` | 不可变流水（append-only，仅追加） | amount_delta_cents, kind, ref_id, created_at |
| `credit_reservations` | 未结算预占 | goal_id, amount_cents, status, expires_at |
| `credit_accounts` | 余额快照（派生，可重建） | balance_cents, reserved_cents |

**校验公式（不可变式）**：

```
可支出 = balance_cents - reserved_cents
校验通过 <=> 预估费用 <= 可支出
```

**校验必须同时在三处执行**：

| 层 | 职责 | 时机 |
|----|------|------|
| API 网关 | 快速拒绝明显超额（余额为 0 等），不查预占 | 请求进入时 |
| 调度器（Hatchet 任务入口） | **权威校验 + 预占**（唯一写reserved 的地方） | 任务启动时 |
| 图节点循环 | 运行中累计校验，超80% 预警 / 100% 熔断 | 每 N 步 |

**为什么落点在调度器而非网关**：网关做不了预占——网关不知道任务的预估成本（那是 Planner 算出来的，在图内部），也无法保证预占与任务启动的原子性。调度器是唯一同时掌握「预估成本」和「任务即将开始」两个信息的地方。

## Alternatives Considered

### 方案 A：仅在 API 网关校验

**评分：1 / 5**

否决理由：网关只能看到请求，不知道预估成本；且无法预占——预占必须在"任务即将开始"这个原子时刻做，网关做不到。并发下必然超卖。

### 方案 B：仅在图内部校验

**评分：2 / 5**

| 问题 | 后果 |
|------|------|
| 已预占成本但未执行 | 白占额度，用户额度被"幽灵任务"冻结 |
| 无事务边界 | 预占写入与任务入队不在同一事务，失败时额度泄漏 |
| 无法在 UI 解释 | 用户看到"任务已被拒绝"但不知道为什么 |

**拒绝在图内部作为唯一校验点**。图内部校验只能作为第三道防线（防止长任务跑超），不能作为权威校验。

### 方案 C：仅靠 PostgreSQL 行锁（`SELECT ... FOR UPDATE`）

**评分：3.5 / 5**

```sql
BEGIN;
SELECT balance_cents, reserved_cents FROM credit_accounts
  WHERE tenant_id = $1 FOR UPDATE;   -- 行锁串行化
-- 校验
INSERT INTO credit_reservations(...);
UPDATE credit_accounts SET reserved_cents = reserved_cents + $2;
COMMIT;
```

| 维度 | 评分 | 依据 |
|------|------|------|
| 正确性 | 5 | 数据库行锁天然串行化，无竞态 |
| 性能 | 4 | 同租户串行，但预占是低频操作（任务启动时），不是热路径 |
| 复杂度 | 5 | 只用数据库，无额外组件 |
| 分布式一致性 | 3 | 若未来跨库/跨区需要更复杂的方案 |

**这是正确的基础方案，但不足以单独使用**——见 §并发锁的补充说明。

### 方案 D：预占-确认-释放两阶段账本 + 行锁 + Redis 锁（选中）

**评分：4.5 / 5**

在方案 C 之上加：不可变流水表 + Redis 快速失败层 + 超时释放机制。

| 维度 | 评分 | 依据 |
|------|------|------|
| 正确性 | 5 | 数据库行锁是权威，Redis 只是快速失败 |
| 可审计 | 5 | append-only 流水可完整重放，余额可由流水重建校验 |
| 崩溃恢复 | 5 | 预占带 `expires_at`，孤儿预占自动释放 |
| 成本控制 | 4 | 多一张流水表 + 定时清理任务，约 +300 行 |

**否决"仅 Redis 分布式锁"作为权威**：Redis 锁在网络分区/主从切换/锁续期失败时可能失效，且 Redis 锁不能提供数据库级的持久性保证。对钱的账务，**权威必须在数据库**。

**否决"仅 Redis 原子计数器"**（`INCRBY` 判断预算）：Redis 是内存存储，AOF 每秒刷盘，宕机会丢最近一秒的账务数据。钱的账不能容忍。

### 方案 E：预付费强制（余额充足才允许创建任务）

**评分： 2.5 / 5**

比方案 A 好一点（可以在创建任务时校验），但仍有竞态：多个任务同时创建时读到相同余额。且**预估成本在任务创建时不可知**（Planner 还没跑），无法精确校验。

## 详细设计

### 1. 三阶段账本

```
阶段 1: RESERVE（预占，任务启动时）
  BEGIN;
  SELECT balance, reserved FROM credit_accounts WHERE tenant_id=$1 FOR UPDATE;
  if balance - reserved < estimated: ROLLBACK -> 拒绝(402)
  INSERT INTO credit_reservations(goal_id, amount, expires_at, status='reserved');
  UPDATE credit_accounts SET reserved = reserved + estimated;
  COMMIT;

阶段 2: SETTLE（确认，任务结束/熔断时）
  BEGIN;
  UPDATE credit_reservations SET status='settled', actual_amount=$2;
  UPDATE credit_accounts
     SET balance = balance - $2,          -- 实扣
         reserved = reserved - estimated;  -- 释放预占
   WHERE tenant_id=$1;
  COMMIT;
  -- 差额（预占 - 实际）自动退回balance

阶段 3: RELEASE（释放，任务失败/预占超时）
  BEGIN;
  UPDATE credit_reservations SET status='released';
  UPDATE credit_accounts SET reserved = reserved - estimated;
  COMMIT;
```

**阶段 2 的关键设计**：余额按**实际**扣，不按预占扣。预估是上界，实际通常更低（LLM 输出长度不确定）。差额自动退回，用户不会被多扣。

### 2. 账本不可变式（必须验证）

```sql
-- 任何时刻必须成立，CI 中作为断言测试
ASSERT credit_accounts.balance >= 0;
ASSERT credit_accounts.reserved >= 0;
ASSERT credit_accounts.balance - credit_accounts.reserved >= -1e-9;  -- 可支出非负
-- 且：reserved 之和 = reservations 表中 status='reserved' 的 amount 之和
```

### 3. 超时释放（防止额度泄漏）

预占后进程崩溃 → 预占永久占用额度 → 用户额度被"幽灵任务"冻结。

```sql
-- 每 60 秒运行的清理任务
UPDATE credit_reservations SET status='expired'
 WHERE status='reserved' AND expires_at < now()
RETURNING goal_id, tenant_id, amount;
-- 对返回结果同步 UPDATE credit_accounts SET reserved = reserved - amount
```

`expires_at` 设置规则：`max(预估时长 × 2, 2小时)`。任务正常结束会走 SETTLE（status 变 settled），清理任务只碰 `status='reserved'` 的，不冲突。

### 4. 三道校验的职责边界

| 层 | 检查什么 | 拒绝时| 是否写库 |
|----|---------|--------|---------|
| API 网关 | 余额 > 0、账号状态正常 | 快速 402，不查预占 | **否** |
| 调度器（权威） | `balance - reserved >= estimated` | 402 + 推送通知 | **是**（写预占） |
| 图节点循环 | 累计花费 / 预估 > 80% | 预警事件（不阻断） | 否 |
| 图节点循环 | 累计花费 >= 预估 × 1.5 | 触发熔断 | 否 |

**为什么 API 网关不查预占**：网关是热路径，每请求查一次预占表会放大 DB 压力且通常没必要（余额为 0 的账号少）。网关只做最廉价的判断，真正的并发安全交给调度器。

**为什么不引入熔断阈值就停止**：PRD 要求「达 100% 停止并推送待办」。这里的 100% 指的是**月度预算**（编制级），不是单任务预估。实现为：图循环检查**当月该编制的累计花费**，达100% 则**拒绝新任务启动**（调度器层）+ **中止正在跑的任务**（图循环层）。这与预算是两个不同粒度的闸门，需分别实现。

### 5. 并发锁的补充说明

方案 C/D 都用了 `SELECT ... FOR UPDATE`。需注意：

- **行锁粒度**：`credit_accounts` 每个租户一行 → 同租户预占串行
- **锁等待超时**：必须设 `lock_timeout = '3s'`，防止恶意长事务把行锁拖死
- **死锁避免**：预占和 settle 按**固定顺序**加锁（永远先锁 accounts 再锁 reservations），避免交叉
- **不需要分布式锁**：单库行锁已足够。引入 Redis 锁只会增加复杂度，且Redis 锁的正确性弱于 DB 行锁

**明确结论：MVP 不引入 Redis 分布式锁做预占。** PostgreSQL 行锁是唯一权威。Redis 只用于图节点循环的累计花费快速读取（可容忍最终一致）。

### 6. 数据模型

```sql
CREATE TABLE credit_accounts (
  tenant_id        UUID PRIMARY KEY REFERENCES tenants(id),
  balance_cents    BIGINT NOT NULL DEFAULT 0,   -- 可用余额（实际）
  reserved_cents   BIGINT NOT NULL DEFAULT 0,   -- 已预占
  CHECK (balance_cents >= 0),
  CHECK (reserved_cents >= 0),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE credit_reservations (
  idUUID PRIMARY KEY DEFAULT gen_random_uuid(),
  goal_id          UUID NOT NULL,
  tenant_id        UUID NOT NULL REFERENCES tenants(id),
  amount_centsBIGINT NOT NULL,
  actual_cents     BIGINT,                        -- SETTLE 时填
  status           TEXT NOT NULL,                 -- reserved/settled/released/expired
  expires_at       TIMESTAMPTZ NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_res_active ON credit_reservations(tenant_id)
  WHERE status = 'reserved';   -- 部分索引，热路径快

CREATE TABLE credit_ledger (
  id               BIGSERIAL PRIMARY KEY,
  tenant_id        UUID NOT NULL,
  amount_delta_cents BIGINT NOT NULL,             -- 正=入账，负=出账
  kind             TEXT NOT NULL,                 -- topup/consume/refund/gift/expire
  ref_id           TEXT,                          -- goal_id / payment_id
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- append-only：REVOKE UPDATE, DELETE
```

## Consequences

### 正面

- **杜绝超卖**：数据库行锁串行化预占，并发任务不可能同时通过校验
- **余额可审计**：`credit_ledger` append-only，可完整重放校验 `credit_accounts` 是否正确
- **不冻结额度**：预占超时自动释放，进程崩溃不泄漏额度
- **不超扣**：settle 按实际扣，差额退回
- **账务可重建**：从 `credit_ledger` 可重算出任意时刻余额，用于对账

### 负面

**必须写进 Spec 的五条约束**：

1. **`credit_accounts` / `credit_ledger` 必须启用 RLS**（ADR-003 同款FORCE + SET LOCAL）
2. **`credit_ledger` 必须 REVOKE UPDATE, DELETE**（append-only，与审计日志同等级别）。账务流水可篡改 = 账务系统不可信
3. **预占和 settle 必须设 `lock_timeout = '3s'`**，并按固定顺序加锁（accounts → reservations）防死锁
4. **`balance - reserved` 在任何时刻必须 >= 0**。这是 CI 断言测试的硬条件，不是运行时靠判断
5. **不允许"仅 Redis 计数"作为权威**。Redis 可用于快速读取，但权威账务必须落 PostgreSQL

**其他负面**：

- **同租户预占串行**：预占是低频操作（任务启动时），不构成性能问题。但如果未来出现"每租户每秒百次任务启动"的场景，需改为分片预占（预留独立额度池），MVP 不需要
- **两张表的维护成本**：`credit_accounts` 是派生数据，需定期与 `credit_ledger` 对账（建议每日凌晨全量重算并比对，差异 > 0 即告警）

## Related ADRs

- ADR-010（治理层）—— 费用统计与配额
- ADR-011（长任务引擎）—— 图节点循环层的累计校验依赖本ADR 的预占
- ADR-003（多租户 RLS）—— credit_* 表必须在租户隔离内

## Verification

**存在性核验**：

```bash
psql -c "\d credit_accounts"
psql -c "\d credit_reservations"
psql -c "\d credit_ledger"
```

**端到端验证步骤**：

1. **超卖阻断（核心用例）**：
   - 账户余额 = 100 元
   - **并发**提交 5 个预估 30 元的任务
   - 断言：至多 3 个通过预占（第4 个起被拒，402）
   - 断言：`SELECT SUM(amount) FROM credit_reservations WHERE status='reserved'` <= 100
   - 断言：**绝不允许 5 个任务全部进入执行**
2. **余额不可超卖**：
   - 断言：全库任一时刻 `balance - reserved >= 0`（CI 断言）
   - 断言：`balance >= 0`
3. **按实际结算**：
   - 预占 30，实际消耗 22
   - 断言：`balance` 只减22（不減 30）
   - 断言：`reserved` 减 30
   - 断言：差额 8 自动在 balance 中可用
4. **预占超时释放**：
   - 造一个预占后 worker崩溃的任务
   - 断言：60 秒后清理任务将其标记 `expired`
   - 断言：额度退回，用户可再次发起任务
   - 断言：**额度未被永久冻结**
5. **ledger append-only（阻断级）**：
   - 尝试 `UPDATE credit_ledger SET amount_delta_cents = 0`
   - 尝试 `DELETE FROM credit_ledger`
   - 断言：**均失败**（权限拒绝）
6. **对账一致性**：
   - 跑 100 个随机任务（含失败/部分失败/熔断）
   - 断言：从 `credit_ledger` 重算的余额 == `credit_accounts.balance`
7. **并发 settle**：
   - 同一租户 20 个任务同时结束
   - 断言：无死锁（无 lock_timeout 异常）
   - 断言：`reserved` 最终归零，无残留
8. **PRD 验收标准逐条验证**：
   - 余额 0.5 元，预估 3 元 -> 阻断，402，提示充值
   - 预算已用 200/200 -> 下一个定时任务**不执行**，推送待办
   - 预算已用 160/200（80%）-> 任务正常完成 + 预警推送
9. **行锁超时保护**：
   - 人为持有行锁 5 秒
   - 断言：新预占请求在 3 秒后报lock_timeout，**不挂死**

第 1、5 条为阻断级。第 1 条（超卖阻断）是本 ADR 存在的唯一理由，必须重点验证。