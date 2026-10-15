# ADR-016: 图标名可导入性验证门禁 + S1 无进展检测签名缺陷修正

## Status
Accepted (2026-10-14)

## Background

本 ADR 记录两件事，都是在 Phase 1.5 交叉检查中发现的**真实缺陷**，不是讨论：

1. **图标名可导入性**：设计师对 `lucide-react@1.57.0` 做实包验证，发现 5 个语义图标名会导致构建失败。其中一个错误来自她自己先前的文档。
2. **S1 无进展检测的签名缺陷**：PM 在追问「F6-lite 阶段是否需要跑误杀测试」时，我重新推演了 S1 的判定逻辑，发现**我设计的 S1 会误杀合法的周期性工作**。这是我自己的设计缺陷。

两个缺陷有同一个共同点：**纸面上看起来对，实际会坏**。这正是知识库 `generated-code-failure-modes.md` 所说的「沉默逻辑错误」——编译通过、跑得动、结果错。

## Decision

### 一、图标门禁：验证方法 + 锁定的正确名称

**核心发现：查文档站会误判。**

`lucide.dev/icons` 的 HTML 页面会保留**已被移除的旧文件**。本次 `CircleHelp` 与 `Filter` 就是这种陷阱——**文件存在于仓库，但没有 PascalCase 导出**，import 会得到 undefined。只看文档站会误判为「可用」。

**唯一可靠的验证方法**：`npm pack` 解包后比对 `dist/lucide-react.d.ts` 的 `declare const` 导出列表。

```
npm pack lucide-react@1.57.0
tar -xzf lucide-react-1.57.0.tgz
grep "declare const <NAME>:" package/dist/lucide-react.d.ts
```

**我已独立复现设计师的全部 5 条修正，逐条验证通过**（`lucide-react@1.57.0` 实包比对）：

| 错误名称 | 实包结果 | 正确名称 | 实包结果 |
|---------|---------|---------|---------|
| `UploadCloud` | MISSING | `CloudUpload` | OK |
| `ShieldQuestion` | MISSING | `ShieldQuestionMark` | OK |
| `CircleHelp` | MISSING（**文件存在但无导出**） | `BadgeQuestionMark` | OK |
| `Filter` | MISSING（**文件存在但无导出**） | `ListFilter` | OK |
| `Building2` | MISSING | `Building` | OK |

**同时验证 9 个 Lucide 1.0 改名全部已移除**（不可再用）：
`AlertTriangle` / `AlertCircle` / `AlertOctagon` / `CheckCircle2` / `XCircle` / `BarChart3` / `LineChart` / `PieChart` / `Loader2`

**我架构文档 §8.3 自己用的 4 个图标验证通过**：`Bot` / `CircleCheck` / `CircleX` / `LoaderCircle`

**实包导出总数**：3782 个 `declare const`（含各命名空间变体）。

**新增 CI 门禁（P0，阻断级）**：

```bash
# scripts/verify-icons.sh —— 进 CI，失败即阻断
set -euo pipefail
npm pack lucide-react@1.57.0 --silent
tar -xzf lucide-react-1.57.0.tgz
DTS=package/dist/lucide-react.d.ts
fail=0
# 从语义映射表逐行读取并验证
while read -r name; do
  [ -z "$name" ] && continue
  if ! grep -q "declare const ${name}:" "$DTS"; then
    echo "ICON MISSING: $name"; fail=1
  fi
done < docs/semantic-icon-map.txt
exit $fail
```

**硬约束**：任何新增图标必须先进 `semantic-icon-map.txt`，由脚本验证通过后才允许写进代码。**禁止"先写 import 再验证"**。

### 二、S1 检测缺陷修正（我自己的设计错误）

**PM 的问题**：「F6-lite 只有 S1（零误判），那 F6-lite 阶段还需要跑误杀测试吗？」

**回答：需要，而且更重要的是——我原先声称 S1「零误判」是错的。**

#### 缺陷推演

我原设计的 S1：「取最近 K=5 步的工具调用签名序列哈希，若命中曾出现的窗口则立即熔断」。

**问题在于「工具调用签名」的定义。若签名只含 `tool_name`：**

```
任务：下载 50 个竞品页面（合法的周期性工作）
序列：fetch_url → parse_html → fetch_url → parse_html → fetch_url → parse_html → ...

窗口 K=5 的内容在第 5 步与第 1 步完全相同
→ 哈希命中 → 判定「重复工具序列」→ 立即熔断
```

**这是一个会大量误杀的缺陷。** 「下载 N 个页面」「逐行处理 N 条记录」「批量调用同一接口」这类**极其常见**的合法工作，全都会被误判为死循环。

这比单纯的阈值问题严重得多——它会让 F6-lite 在真实使用中频繁误停，而熔断误停对信任的伤害极大（PM 已独立指出「误杀比没熔断更糟」）。

#### 修正后的签名定义

**签名必须包含「工具名 + 归一化参数摘要」，而非仅工具名。**

```python
# 修正前（错误）：签名只含工具名
sig = step.tool_name
# → fetch, parse, fetch, parse 周期即命中

# 修正后（正确）：签名含归一化参数摘要
def tool_signature(step) -> str:
    """工具名 + 参数归一化摘要。参数不同则签名不同。"""
    norm = normalize_args(step.args)      # 见下
    return f"{step.tool_name}({norm})"

def normalize_args(args: dict) -> str:
    """参数归一化：路径参数保留（因为循环索引在参数里），
       内容参数用哈希（因为内容每次都变）"""
    parts = []
    for k in sorted(args.keys()):
        v = args[k]
        if k in PATH_LIKE_KEYS:        # url / index / page / offset / id
            parts.append(f"{k}={v}")           # 保留原值——这是区分循环的关键
        else:
            parts.append(f"{k}={hash(v)}")# 内容哈希
    return ",".join(parts)
```

**关键点**：`url` / `page` / `index` 这类**循环索引参数必须保留原值**，因为区分「循环推进」和「原地打转」的正是它们。

| 场景 | 修正前 | 修正后 |
|------|-------|-------|
| 下载 50 个页面（url 每次不同） | 误杀（第 5 步命中） | **正确放行**（签名含 url，逐个不同） |
| 原地重试同一失败 url | 误杀 | **正确熔断**（签名完全相同） |
| 死循环调同一工具同参数 | 误杀 | **正确熔断** |

#### 修正后的判定分级

```
S1a  签名序列完全重复（含参数）连续 N1=5 步  -> 硬熔断   [确定性，误报极低]
S1b  签名序列重复但参数在推进（如 url 索引递增）-> 不熔断，只计数
```

**S1a 仍不是「零误判」**，但误报条件已收窄到「工具名与参数完全一致地重复 5 次」——这在合法工作中几乎不可能出现（若参数不变，任务本身就没有推进）。

**降级影响**：修正后 S1 的判定强度略降，因此 **F6-lite 必须补 S2（产出物增量）作为第二道防线**。原方案中 S1 单独承担熔断职责的设计不再成立。

### 三、误杀测试的阶段归属（回答 PM）

**F6-lite 与 F6-full 都必须跑误杀测试，且 F6-lite 的误杀测试更重要。**

| 阶段 | 检测信号 | 误杀测试归属 | 理由 |
|------|---------|------------|------|
| **F6-lite** | S1a（含参数签名）+ **S2 产出物增量** | **必须，阻断级** | S1a 收窄后误报率降低但非零；S2 是新增信号，其阈值需实测调参 |
| F6-full | S1a + S2 + S3 外部副作用 + S4 状态指纹 | 必须，阻断级 | S3/S4 是新信号，各自需误杀验证 |

**F6-lite 的阻断级误杀测试用例**（PM 已写进验收标准，我补齐实现口径）：

| 用例 | 预期 |
|------|------|
| 下载 50 个竞品页面（url 递增） | **全程不熔断** |
| 逐行处理 100 条 Excel 记录（index 递增） | **全程不熔断** |
| 批量调用同一接口 30 次（id 递增） | **全程不熔断** |
| 原地重试同一失败 URL | 第 5 次熔断 |
| 参数固定的死循环 | 第 5 次熔断 |

**这五条是 F6-lite 上线的阻断条件。** 前三条是「不许误杀」，后两条是「必须能杀」。

## Consequences

### 正面

- **图标构建失败在 CI 阶段暴露**，不再在 Phase 3 前端开发时才发现
- **验证方法可复现**：实包比对而非查文档站，不受文档站滞后的影响
- **S1 缺陷修正后，周期性合法工作不再被误杀**——这直接影响 F6-lite 能否在真实岗位中可用
- **误杀测试有明确阶段归属与用例清单**，不是笼统的「测一下」

### 负面

**五条必须落进 Spec 的约束**：

1. **图标必须先进 `semantic-icon-map.txt` 再写代码**，CI 脚本验证 `declare const` 导出存在。禁止先写 import 再验证
2. **禁止以 lucide.dev/icons 或任何文档站作为可用性依据**。该站保留已移除的旧文件（`CircleHelp`/`Filter` 即是），会给出假阳性
3. **S1 签名必须含归一化参数摘要**，且 `url`/`index`/`page` 等循环索引参数**保留原值**（内容参数用哈希）。仅含工具名的签名是错误实现
4. **F6-lite 必须包含 S2（产出物增量）**，不能只靠 S1a。S1a 收窄后不足以单独承担熔断职责
5. **五条误杀用例为 F6-lite 阻断级**，前三条（不许误杀）优先级不低于后两条（必须能杀）。熔断系统的误报率是产品生死项

**其他负面**：

- **图标名锁定会随 lucide 版本变化失效**。升级 lucide 版本时必须重跑验证脚本。这个约束要写进依赖升级流程（ADR-006 已要求锁定精确版本）
- **S1a 的「几乎不误杀」是工程判断，非数学证明**。仍需在真实任务上持续观测误报率并调 N1 参数。这条要进运维监控：熔断触发后记录当时的任务类型与签名序列，定期复盘

## Related ADRs

- ADR-006（前端栈与图标库）—— 本 ADR 是其可执行验证门禁的补充
- ADR-011（长任务引擎）—— S1 签名缺陷的修正在此固化
- ADR-014（网页访问分级）—— 「下载 50 个竞品页面」正是 ADR-014 的典型场景

## Verification

**存在性核验**：

```bash
npm pack lucide-react@1.57.0
tar -xzf lucide-react-1.57.0.tgz
grep "declare const CloudUpload:" package/dist/lucide-react.d.ts
```

**端到端验证步骤**：

1. **图标门禁生效**：
   - 在 `semantic-icon-map.txt` 写入一个不存在的名字（如 `ThisIconDoesNotExist`）
   - 跑 `scripts/verify-icons.sh`，断言：**退出码非 0 并打印 MISSING**
   - 断言：CI 阻断
2. **旧名不可用（回归）**：
   - 断言：`UploadCloud`/`CircleHelp`/`Filter`/`Building2`/`ShieldQuestion` 全部 MISSING
   - 断言：9 个 1.0 旧名全部 REMOVED
3. **S1 签名修正（阻断级）**：
   - 造「下载 50 个页面，url 递增」任务
   - 断言：**全程不熔断**（修正前会在第 5 步误杀）
   - 断言：修正确实生效——用仅含 tool_name 的签名跑同一任务，**应当误杀**（证明测试有区分力）
4. **S1 仍能杀真死循环（阻断级）**：
   - 造「参数完全固定的死循环」
   - 断言：第 5 次签名重复时熔断
5. **S2 在 F6-lite 中生效**：
   - 断言：F6-lite 的判定逻辑包含 S2，不只有 S1
6. **误杀率可观测**：
   - 断言：每次熔断都记录任务类型 + 签名序列 + 触发信号
   - 断言：这些记录进运维看板，可定期复盘误报率

第 3、4 条为阻断级。第 3 条尤其重要——**它必须能证明修正前后的行为差异**，否则测试本身无区分力，测了也白测。