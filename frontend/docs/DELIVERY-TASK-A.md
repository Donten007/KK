# 任务 A 交付报告 —— 项目骨架 + 认证

```
verdict: pass
blocking: []
generated: Phase 3
```

## 1. 证据

| 项 | artifact_ref | 说明 |
|---|---|---|
| 工程骨架 | `frontend/package.json` | Next 16.4.0 / React 19.3.0 / Tailwind 4.3.3 / TS 5.9.3 / lucide-react 1.57.0，**全部精确锁版本，无 `^`/`~`** |
| Token 接入 | `frontend/src/styles/globals.css:1` | `@import '../../../design-system/design-tokens.css'` —— **直接引用设计师原件，未复制**。深浅主题走 `[data-theme]`，暗色默认 |
| 类型契约 | `frontend/src/types/api.d.ts` | `openapi-typescript` 从 `docs/openapi.yaml` 生成，3877 行，**零手写请求/响应类型** |
| 认证 | `frontend/src/lib/api/auth.ts` | 对接 `POST /api/v1/auth/{register,login,refresh,logout}` + `GET /auth/me` |
| 路由守卫 | `frontend/src/lib/auth/require-session.ts` | 未登录 `redirect('/login?next=…')` |
| 布局骨架 | `frontend/src/components/shell/` | 侧栏 240/56px + 顶栏 + 移动端 TabBar |
| 登录页 | `frontend/src/app/login/page.tsx` | UIUX §7.2 **反 Hero**：左真实工作台缩略预览，右登录表单 |
| P0 门禁 | `frontend/scripts/verify-p0.sh` | 6 项自动门禁 |

## 2. 自检结果

```
lint        PASS  (eslint 9.39.5 + eslint-config-next 16.4.0)
type-check  PASS  (tsc --noEmit, 0 error)
build       PASS  (Next 16.4.0 Turbopack, 3 routes)
verify:p0   PASS  (6/6)
```

P0 门禁全项：emoji 0 命中 / 组件层裸 hex 0 命中 / 弹跳缓动 0 / 紫粉渐变+渐变文字+左色条 0 / 超 300 行文件 0 / **25 个图标名逐个核对 lucide-react 真实导出全部存在**。

## 3. 任务 A 达成度：完成

侧边导航只暴露 2 项（每日汇报 / 岗位库）。**没有为 Phase 3 的页面放占位入口** —— 一个点了跳 404 的导航项比没有这个导航项伤害更大：老板无法区分「功能没做」和「系统坏了」。Phase 3 上线时在 `nav-config.ts` 加一行即可。

## 4. 放行条件 1（认证 + RLS 隔离）的前端部分

前端侧已就绪（登录/注册/守卫/登出/token 轮换）。**端到端验证需后端启动** —— 后端未启动时无法证明 RLS 隔离生效，该项不签 pass，只签「前端部分完成」。

## 5. 需要裁决的 3 件事

### ① 版本幻觉依赖，已拦下

SPEC 未锁 `eslint` / `@types/*` 版本。初稿写了 `eslint@9.42.0`、`@types/react@19.3.7` 等 4 个版本，**npm 上全部不存在**，安装直接失败。已实测修正为：

```
eslint         9.42.0  →  9.39.5
@types/react   19.3.7  →  19.3.0
@types/react-dom 19.3.5 → 19.3.0
@types/node    22.20.0 →  22.20.5
```

建议：把存在性核验扩展到全部依赖（装前核版本）。

### ② token 存储的安全权衡（前端自行决定，需确认）

access token 存内存、refresh token 存 localStorage。理由：access token 放内存降低长期窃取面；refresh token 必须跨会话存活，否则老板每次刷新都要重登。

**这是骨架期取舍，不是终态安全方案。** 若后端能改为 httpOnly cookie 下发 refresh token，立即替换。

### ③ 成本区块两处「无数据」选择留空，未编造

UIUX §8.1 允许在成本构成里显示「环比 ↑2.1%」与「约 4 小时人工」，但 `CostBreakdown` schema **没有环比字段，也没有工时字段**。

处理：这两项**不渲染**，并在 `cost-breakdown-panel.tsx` 注明「后端补字段后在此实现」。

理由：SPEC §8.5 把「无数据时编造」定为 P0 缺陷（信任指标造假 = 在信任指标里投毒）。给一个恒为「持平」的环比比不给更糟 —— 老板会以为成本真的没变。

**需确认：这两组数据 Phase 2 补不补？** 若补，按 UIUX §8.1 实现（趋势必须带方向符号 + 数值，禁止只用颜色）。

## 6. 设计契约冲突

无。UIUX §7.2 / §7.3 / §11.1 / §12 全部照做，未自行改设计。