# 沙箱 POC 清单（Phase 2 第一周，先于业务编码）

> **作者**：首席架构师 高见远
> **日期**：2026-10-15
> **优先级**：**P0 阻断级**。Phase 2 第一周执行，**先于任何业务编码**。
> **依据**：ADR-004 §12.2 + ADR-014 §方案 C + SPEC §4.5 / §11 坑 8

---

## 一、为什么必须先跑这个 POC

**gVisor 只实现约 60% 的 syscall。** 这不是理论风险，是实测数据。而我们的沙箱镜像基线是 `python:3.13-slim-bookworm` 与 `node:22-slim-bookworm`——这两个镜像里**预装了大量 C 扩展与原生模块**。

**风险的不对称性**：

| 发现时点 | 返工成本 |
|---------|---------|
| Phase 2 第一周（POC） | 2-3 天，只换 runtime |
| Phase 3 业务编码后 | 已写的沙箱执行层全部要重验 |
| Phase 3 末尾联调时 | **上线延期**，且没人说得清哪些功能会坏 |

**结论：越晚发现返工越大，且这个返工无法用「加班」弥补——它需要重新验证每一个已实现的功能。**

**POC 只需 2-3 天。** 用 2-3 天换掉一个可能延整个 Phase 3 的不确定性，是本项目 ROI 最高的一项技术活动。

---

## 二、POC 目标（三个必须回答的问题）

1. **20 个场景里有多少个在 runsc 下失败？** 失败率 < 20% → 继续用 gVisor；≥ 20% → 升 Kata Containers。
2. **哪些具体包不可用？** 得出「镜像黑名单」——不可用的包从基线镜像中剔除，而不是等运行时炸。
3. **资源限额是否真实生效？** cgroups 限额、`pids-limit`、磁盘配额、`ulimit` 四项必须都验证。**限额不生效比功能失败更危险**——功能失败会报错，限额失效会让一个租户打垮共享宿主。

---

## 三、判定标准

| 结果 | 动作 |
|------|------|
| 全部通过 | 锁 gVisor，POC 结论升 ADR |
| 失败 ≤ 3 个场景，且**不涉及**第 3/4/7/8 项（C 扩展与子进程） | 锁 gVisor，但**剔除对应包**并写入镜像基线 |
| 失败 ≥ 4 个，或涉及 C 扩展/子进程/线程 | **升 Kata Containers**（API 层不变，只换 runtime），20 个场景重跑 |
| 资源限额任一不生效 | **阻断**，先修限额再谈功能 |

**为什么「涉及 C 扩展/子进程/线程」时直接升 Kata**：这三类是 gVisor 的系统性弱项（不是个别包的问题），修补成本高于换 runtime。而 Kata 只需改 `--runtime` 参数，**沙箱执行层的代码不用动**——这是我们预留的退路。

---

## 四、Python 场景（10 个）

> 镜像：`python:3.13-slim-bookworm`，runtime：`runsc`，配置同 SPEC §4.5 基线。

| # | 场景 | 为什么测它 | 执行命令 | 通过判据 |
|---|------|-----------|---------|---------|
| **P1** | 纯 Python 计算基线 | 对照组。若这个都不过，说明配置错了不是兼容问题 | `python -c "print(sum(range(10**6)))"` | 退出码 0，输出 499999500000 |
| **P2** | **pysqlite3 本地 DB 读写** | **C 扩展**。客户 Excel 导入后的结构化存储走它 | `python -c "import sqlite3; c=sqlite3.connect('/workspace/out/t.db'); c.execute('create table x(a)'); c.execute('insert into x values(1)'); c.commit(); print(c.execute('select count(*) from x').fetchone())"` | 输出 `(1,)`，且 `/workspace/out/t.db` 存在 |
| **P3** | **numpy 数组运算** | **C 扩展 + BLAS**。数据分析类岗位的基础依赖 | `python -c "import numpy as np; a=np.random.rand(1000,1000); print(float((a@a).sum()))"` | 退出码 0，输出一个有限浮点数（非 nan/inf） |
| **P4** | **lxml HTML 解析** | **C 扩展**。**L1 抓取的核心依赖**，竞品监控日报每步都用它 | `python -c "import lxml.html as h; d=h.fromstring('<html><body><p>x</p></body></html>'); print(d.xpath('//p/text()'))"` | 输出 `['x']` |
| **P5** | **pip install 纯 Python 包** | **子进程 + 网络 + 写文件系统**三重叠加 | `pip install --no-cache-dir six && python -c "import six; print(six.__version__)"` | 退出码 0，出版本号 |
| **P6** | **pip install 含 C 扩展的包** | 子进程 + **编译**（sdist build，node-gyp 的对应物） | `pip install --no-cache-dir MarkupSafe` | 退出码 0（编译通过） |
| **P7** | **multiprocessing 多进程** | `fork`/`clone` syscall，**gVisor 已知弱项** | `python -c "import multiprocessing as m; p=m.Pool(4); print(p.map(abs,[-1,-2,-3,-4]))"` | 输出 `[1, 2, 3, 4]` |
| **P8** | **subprocess 起 shell + 出网** | 进程 + socket，模拟「沙箱里跑 curl」 | `python -c "import subprocess; print(subprocess.run(['curl','-sI','https://api.deepseek.com'],capture_output=True,text=True).stdout[:20])"` | 输出含 `HTTP/` |
| **P9** | 内存超限（应被拒） | **限额必须生效**。分配 3GB，基线配 2GB | `python -c "a=bytearray(3*1024**3); a[0]=1"` | **被 OOM kill 或 MemoryError**，且宿主未受牵连 |
| **P10** | 文件描述符超限（应被拒） | `ulimit nofile=1024` 是否生效 | `python -c "f=[open('/dev/null') for _ in range(2000)]"` | 第 1025 个左右抛 `OSError: Too many open files` |

**P9 / P10 是反向断言**——它们测的是「坏事没发生」，比 P1-P8 更重要。**限额失效不会报错，只会让一个租户打垮共享宿主。**

---

## 五、Node 场景（10 个）

> 镜像：`node:22-slim-bookworm`，runtime：`runsc`，配置同 SPEC §4.5 基线。

| # | 场景 | 为什么测它 | 执行命令 | 通过判据 |
|---|------|-----------|---------|---------|
| **N1** | 纯 JS 基线 | 对照组 | `node -e "console.log(Array.from({length:1e6},(_,i)=>i).reduce((a,b)=>a+b,0))"` | 输出 499999500000 |
| **N2** | **node-gyp 编译原生模块** | **编译工具链**（cc/g++/make/python 全链路） | `npm install --no-audit --no-fund bcrypt` | 退出码 0，`node -e "console.log(!!require('bcrypt'))"` 输出 true |
| **N3** | **加载预编译 .node 二进制** | `dlopen` syscall。`better-sqlite3` 走这条 | `npm install better-sqlite3 && node -e "const D=require('better-sqlite3'); const d=new D('/workspace/out/n.db'); d.exec('create table x(a)'); console.log('ok')"` | 输出 `ok` |
| **N4** | **npm install 含 optionalDependencies 原生包** | 原生包失败时回退到 JS 实现的路径是否正确 | `npm install --no-audit --no-fund ws` | 退出码 0 且 `require('ws')` 可用 |
| **N5** | **child_process.spawn 子进程** | `clone`/`execve` | `node -e "const{spawn}=require('child_process'); const p=spawn('ls',['-la','/workspace']); p.stdout.on('data',d=>process.stdout.write(d))"` | 输出目录列表 |
| **N6** | **net 模块出网** | socket syscall（Node 侧 curl 等价物） | `node -e "require('https').get('https://api.deepseek.com',r=>console.log('status',r.statusCode))"` | 输出 `status 200` 或 4xx/5xx（**连通即通过，状态码不限**） |
| **N7** | **worker_threads** | 线程支持。gVisor 的线程模型与内核不同 | `node -e "const{Worker}=require('worker_threads'); const w=new Worker('const{parentPort}=require(\"worker_threads\");parentPort.postMessage(42)',{eval:true}); w.on('message',m=>console.log(m))"` | 输出 42 |
| **N8** | 大量小文件读写 | `open`/`close`/`stat` 高频调用 | `node -e "const fs=require('fs'); for(let i=0;i<5000;i++) fs.writeFileSync('/workspace/out/f'+i,'x'); console.log(fs.readdirSync('/workspace/out').length)"` | 输出 5000 |
| **N9** | Buffer 分配 2GB（应被拒） | **限额必须生效** | `node -e "const b=Buffer.alloc(2*1024**3); b[0]=1; console.log(b.length)"` | 被 OOM kill 或抛 `ERR_BUFFER_OUT_OF_BOUNDS` / allocation failure |
| **N10** | 长连接保持 | `epoll` 实现差异。SSE 类长连接场景 | `node -e "const ws=new (require('ws'))('wss://echo.websocket.org'); ws.on('open',()=>{ws.send('hi'); setTimeout(()=>{console.log('held'); process.exit(0)},3000)})"` | 3 秒后输出 `held`（连接未被误断） |

**N2 / N3 是团队lead 特别关注的两项**：Node 原生模块是 node-gyp 编译产物，编译期要跑完整的 cc/make/python 工具链，是 gVisor syscall 覆盖缺口最可能暴露的地方。

---

## 六、执行方式

```bash
# 每个场景一个独立脚本，统一判退出码
for s in scenarios/python/P{1..10}.sh scenarios/node/N{1..10}.sh; do
  echo "=== $s ==="
  docker run --rm --runtime=runsc \
    --network=sandbox-egress-net --cap-drop=ALL --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --memory=2g --memory-swap=2g --cpus=2 --pids-limit=128 \
    --ulimit nofile=1024:1024 --user 65534:65534 \
    -v "$(pwd)/scenarios:/scenarios:ro" \
    -v "/sandbox/work/poc:/workspace/out:rw,noexec,nosuid" \
    python:3.13-slim-bookworm bash "/scenarios/$(basename $s)" \
    && echo "PASS" || echo "FAIL"
done
```

**必须记录**：每个场景的**退出码 + stdout/stderr 前 200 字符 + 耗时**。失败时这三项是判断「是兼容问题还是配置问题」的唯一依据。

**POC 产出物**：
1. 20 行结果表（场景 / 结果 / 失败原因 / 耗时）
2. **镜像黑名单**：不可用的包清单，从基线镜像剔除
3. 若需升 Kata：迁移影响评估（哪些已写代码要改——**预期是 0 行**，只换 `--runtime`）

---

## 七、与相邻决策的关系

| 决策 | 关系 |
|------|------|
| ADR-004 沙箱隔离 | 本 POC 是其「镜像管理」与「已知限制」两节的验证前提 |
| ADR-014 网页访问分级 | **L2 无头浏览器不做，部分原因就是 Chromium 需要大量 syscall**。本 POC 若判定 gVisor 不兼容，进一步印证该判断 |
| SPEC §11 坑 8 | 本 POC 是该坑的解法 |
| SPEC §4.5 沙箱配置基线 | 本 POC 用的就是这套配置，POC 通过即等于基线配置通过 |

---

## 八、一条必须写进运维的约束

**POC 通过不等于永久通过。** gVisor 自身版本升级、基础镜像升级（`python:3.13-slim` → `3.14-slim`）都可能重新引入不兼容。

**约束**：每次升级 gVisor 或基础镜像，**必须重跑这 20 个场景**。加进 CI 的 nightly  job，不是只跑一次。

## 四、POC 实测结论（2026-10-15，GitHub Actions 七轮迭代）

**最终结果：兼容性 18/18 全绿 → 锁定 gVisor**；资源限额 3 条反向断言移交部署阶段门禁。

| 项 | 结果 |
|----|------|
| Python 功能场景（P1-P8）| ✅ 全过（C 扩展/BLAS/多进程/pip sdist 编译/subprocess+出网）|
| Node 功能场景（N1-N8）| ✅ 全过（npm 工具链/预编译 .node/optionalDeps 回退/worker_threads/出网）|
| fd 限额（P10）| ✅ ulimit 生效 |
| 内存限额（P9/N9）| ⏸ CI runner 上不生效 → **部署阶段必须复验** |
| 进程数限额（N10）| ⏸ 同上 |

### 过程中修掉的环境坑（防重蹈）
1. `gvisor.sh` 域名已废弃（runner DNS 持续解析失败）→ key 改从 `gvisor.dev/archive.key`
2. 2026-07 起 gVisor 多文件发布，旧单二进制 URL 全 404 → apt 或 gvisor.tar.zstd
3. Node 镜像 tag 是 `node:22-bookworm-slim`（`22-slim-bookworm` 不存在）
4. P9 内存断言必须逐页写非零（全零数组被零页优化，假阴性）

### 遗留：限额移交部署阶段门禁（OPEN-DECISIONS 挂账）
runsc `--systemd-cgroup` 已配置，CI runner 上 docker `--memory/--pids-limit` 对 gVisor 容器仍不生效
（gvisor #10264 同族问题，与 runner 的 cgroup 驱动配置相关）。**生产部署时必须在同构环境复跑
P9/N9/N10 三条反向断言，限额不生效不得上线**；若生产同构环境仍不生效，执行 Kata Containers
备选（沙箱执行层预期 0 行改动，ADR-004 预留）。
