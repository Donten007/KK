# EvoWork — 营销级登录/注册页设计规范（UIUX-marketing）

> 阶段：Phase 2（营销页重设计）
> 作者：颜好看（UI/UX 设计师）
> 日期：2026-10-15
> 状态：**Spec 已定稿，待前端实现**
> 配套：`design-tokens.json` v1.1.0 `color.marketing` / `typography.marketingScale` / `layout.marketing`；`design-tokens.css` Section 13
> 范围：**仅 `/login` 与 `/register` 两页**。工作台内部（`(workspace)` 全部路由）维持现有浅色专业风，本文档的一切规则不外溢。

---

## 0. 背景与裁定

**需求来源**：用户反馈现有登录页「有点老土」，指定参照苹果 / 小米 / DeepSeek 官网质感。总监已裁定：

1. 只做登录页 + 注册页的**营销级**重设计；工作台内部不动（Linear/Stripe 双面模式：营销页炫、工作台素）。
2. 深蓝光晕渐变背景方向正确，不违反 P0-2（禁的是紫→粉）。
3. 表单逻辑不变：登录 = 账套号 + 密码；注册 = 账套号 / 邮箱 / 密码。只换视觉容器。
4. 品牌语气务实（PRD：**「给中小企业老板一个不用招人、按时上班、交不出活来自己负责的 AI 员工」**），不喊空洞口号。

**参照图说明**：`_research/deepseek-ref.jpg` 在磁盘上不存在（`_research/` 下仅有 `tree.json`）。本 spec 按总监提供的文字特征执行：深蓝光晕全屏背景、居中超大标题 + 中文副标、灰色小字两行、白色胶囊 CTA、极简毛玻璃导航、大量留白。实现后应与用户做一次视觉走查确认。

---

## 1. 寄存器与三轴刻度

| 维度 | 判定 | 依据 |
|---|---|---|
| 寄存器 | **Brand**（登录/注册即产品门面） | 页面职责是建立第一印象与信任，不是工具操作 |
| 平台轴 | web | — |
| `DESIGN_VARIANCE` | 6（仅此两页） | 居中构图是 DeepSeek 参照的核心特征，**是有意豁免**「>4 禁止居中 Hero」规则——因为这两页的 Hero 就是页面本身，且唯一的转化动作（登录/注册）就在 Hero 正下方，无「大标题后CTA 跳走」的断裂 |
| `MOTION_INTENSITY` | 2 | 背景光晕**完全静态**（永不动画 background-position/filter/opacity）。唯一动效：卡片 200ms 淡入（单元素、单属性、opacity only） |
| `VISUAL_DENSITY` | 2 | 大量留白是参照的核心质感。整页只有：导航 / 标题区 / 表单卡 / 页脚 四个层次 |

**与 `docs/UIUX.md` 的规则冲突裁定**（均为 Brand 寄存器内的有意豁免，写死边界，防止扩散）：

| UIUX.md 规则 | 登录/注册页豁免 | 边界 |
|---|---|---|
| 规则 6「禁装饰性毛玻璃」 | 允许玻璃态表单卡 + 导航 | 毛玻璃**只**用于这两页的功能容器（表单卡/导航），不是装饰贴片；工作台内禁令不变 |
| §5.2「pill 仅限头像和状态胶囊」 | 允许 CTA 白色胶囊按钮 | 每页**仅 1 个**胶囊元素（主 CTA），其余按钮一律 `--radius-md` |
| §3.7「accent 每屏 ≤2 处」 | 光晕中的 `glow-accent` 为效果层（<1% 面积），不计配额 | 页面上可见的 accent 元素仍 ≤2（表单内链接 + focus ring） |
| §4 规则 2「卡片无投影」 | 玻璃卡无投影，深度用 1px inset 高光 + 亮度递进表达 | 不引入 drop shadow，维持「光从背景来不从上方来」 |

---

## 2. 页面结构

### 2.1 登录页 `/login`（纵向单列，全部居中）

```
┌────────────────────────────────────────────────────┐
│ [mkt-nav]  logo EvoWork          没有团队？注册 →   │ 64px，毛玻璃，sticky
│                                                    │
│                  （96px 间距）                      │
│                                                    │
│           你的 AI 员工，刚交了新汇报。               │ ← display-xl 64px/590
│                                                    │
│      登录后查看每个员工的产出、汇报与成本。          │ ← lead 18px，最多 2 行
│                                                    │
│              （48px 间距）                          │
│         ┌──────────────────────────┐               │
│         │  〈登录 | 注册〉切换        │               │ ← Segmented Control（沿用现有）
│         │  账套号                   │               │
│         │  [                    ]  │               │ 44px 高
│         │  密码                    │               │
│         │  [                    ]  │               │
│         │        [ 登录 ]          │               │ ← 白色胶囊 48px
│         │  忘记密码？               │               │ 14px 链接
│         └──────────────────────────┘               │
│              420px 玻璃卡                           │
│                                                    │
│         （96px 间距）                               │
│    〈真实工作台预览条（现有 WorkbenchPreview，       │ ← 可选区块，见 §2.3
│      桌面端显示，静态）〉                            │
│                                                    │
│  © EvoWork · AI 员工的雇佣与调度平台                │ ← 页脚，14px muted
└────────────────────────────────────────────────────┘
```

### 2.2 注册页 `/register`

同壳，三处差异：

| 元素 | 登录页 | 注册页 |
|---|---|---|
| 主标题 | 你的 AI 员工，刚交了新汇报。 | 雇下第一个 AI 员工。 |
| 副标题 | 登录后查看每个员工的产出、汇报与成本。 | 写好岗位说明书，它今天就上岗。按结果看产出，不按过程烧时间。 |
| 表单字段 | 账套号 / 密码 | 账套号 / 邮箱 / 密码（沿用现有 AuthForm 逻辑与校验） |
| 导航右侧链接 | 没有团队？注册 → | 已有团队？登录 → |
| CTA 文案 | 登录 | 创建团队 |

### 2.3 关于 WorkbenchPreview

保留「展示真实产品形态」的原则（UIUX.md §7.2 反 Hero 模式的精神延续），但从主角降级为**衬底证据**：

- **桌面端（≥1024px）**：表单卡下方 96px 处，显示现有 `WorkbenchPreview` 的静态预览条（等宽 720px，降低透明度至 85%，1px `--mkt-glass-border` 边框）。作用：让「AI 员工真的在干活」有实物证据，这是 BYOK 务实品牌的关键信任点。
- **移动端 / <1024px**：不渲染（首屏只留标题+表单，降低跳出率）。

---

## 3. 背景光晕 — CSS 实现要点

**全部色值走 token**（Section 13 已定义），组件代码零裸 hex。画布是 `position: fixed; inset: 0; z-index: -1` 的独立层，不与内容层耦合。

### 3.1 三层叠加（自下而上）

```css
/* 层 1（最底）：垂直亮度递进 —— 顶部略亮制造纵深，62% 处沉入底色 */
linear-gradient(180deg, var(--mkt-bg-elev) 0%, var(--mkt-bg) 62%)

/* 层 2：主光晕，右上。椭圆 900x600，中心 (75%, 10%)，alpha 0.30，60% 处消散 */
radial-gradient(ellipse 900px 600px at 75% 10%,
  color-mix(in srgb, var(--mkt-glow-primary) 30%, transparent), transparent 60%)

/* 层 3：副光晕，左下。椭圆 700x500，中心 (10%, 90%)，alpha 0.20，55% 处消散。
   作用：右上有光时左下必须有暗部呼应，否则画面失重 */
radial-gradient(ellipse 700px 500px at 10% 90%,
  color-mix(in srgb, var(--mkt-glow-secondary) 20%, transparent), transparent 55%)
```

三层写在同一个 `background` 声明里（顺序即层序），见 `.mkt-canvas`。**不要**拆成三个 div 叠加——层多一倍，维护翻倍。

### 3.2 品牌微光斑（可选第二档）

表单卡正后方允许放**一个** `.mkt-glow-blob`：`--mkt-glow-primary` 实色圆 + `filter: blur(120px)` + `opacity: 0.10`，直径约 560px，中心对齐卡片。作用是把品牌青蓝（hue 191）压进深蓝画面，让「光晕」不只是氛围色而是品牌色。

- 每页**最多 1 个**光斑 div。`pointer-events: none` 必须加。
- 与 3.1 的层叠式光晕二选一即可同页共存（层叠做氛围，光斑做聚焦），但**禁止**再加第三层。

### 3.3 硬性禁令

- 光晕任何属性（position / filter / opacity）**永不动画**——背景动了，表单就静不下来。
- 光晕色相锁定在蓝-青域（210/209/191）。禁止引入 240°+（紫域）或 330°+（粉域）的任何中间色——这是 P0-2 的物理隔离，不是审美偏好。
- `color-mix` 的 alpha 只在 CSS 里施加，token 本体存实色值——保证 `design-tokens.json` 可被非 CSS 消费方（RN/Flutter 迁移）直接用。

---

## 4. 关键组件规格

### 4.1 主标题（display 阶梯）

| 断点 | token | 字号/行高/字距 | 字重 |
|---|---|---|---|
| ≥1280px | `display-xl` | 64px / 72px / -0.02em | 590 |
| 768–1279px | `display-lg` | 48px / 56px / -0.015em | 590 |
| <768px | `display-md` | 36px / 44px / -0.01em | 590 |

- 字重**锁定 590**。参照站的大标题其实不粗——大字号 + 负字距承担了全部力度，700+ 中文黑体在深底上会糊。全局 700 禁令不豁免。
- 标题颜色 `--mkt-fg-1`（13.8:1 AAA）。**禁止**渐变文字、禁止 accent 色标题。
- 标题必须带句号——这是 DeepSeek 参照里最容易被漏掉的细节：完整句子 + 句号 = 产品在陈述事实，不是在喊口号。
- 副标题：`--mkt-text-lead` 18px/30px，`--mkt-fg-2`（9.3:1 AAA），`max-width: 32em`（约两行），居中。

### 4.2 导航（mkt-nav）

- 高 64px，sticky top-0，`.mkt-glass` 材质（blur 20px + 1px 底部 hairline `--mkt-glass-border`，无圆角——通栏）。
- 内容：左 logo（图标 24px + 「EvoWork」 16px/590），右侧一个文字链接（`--mkt-nav-fg` 14px，hover 转 `--mkt-fg-1` + 下划线 offset 4px）。
- **不加**菜单项、语言切换等参照站冗余——登录页导航的唯一任务是「去对面页」。
- 链接触摸目标 ≥44px（padding 补足）。

### 4.3 CTA 胶囊按钮（mkt-cta）

| 属性 | 值 |
|---|---|
| 尺寸 | 高 48px，水平 padding 24px，表单卡内**占满卡片宽度** |
| 圆角 | `--radius-pill`（本页唯一胶囊） |
| 配色 | `--mkt-cta-bg` 白底 + `--mkt-cta-fg` 深字（18.9:1）；hover `#EBF2F6`（冷调不是灰）；active 同色 + `scale(0.98)` |
| 文案 | 「登录」/「创建团队」，15–16px / 510 / `letter-spacing: 0.01em` |
| 过渡 | background 150ms `--ease-standard`。无 hover 位移、无阴影变化 |
| Loading 态 | 文案换成「正在验证…」+ `LoaderCircle` 16px 旋转（沿用状态库），按钮 disabled |
| 边界 | 每页仅此 1 个胶囊。次级动作（忘记密码、切换登录/注册）一律文字链接 |

**为什么是白底而不是 accent 底**：参照的核心识别就是深蓝画面上的白色胶囊——它是画面里**最亮**的元素，视线第一落点必然是转化按钮。accent 青蓝底在深蓝光晕旁反而失焦。

### 4.4 表单玻璃卡（mkt-glass）

| 属性 | 值 | 说明 |
|---|---|---|
| 宽度 | 420px（<480px 视口时 `calc(100vw - 32px)`） | |
| 内边距 | 32px（移动端 24px） | |
| 圆角 | `--radius-lg` 12px | 卡片圆角上限规则不豁免 |
| 背景 | `linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02))` | token: `--mkt-glass-bg` 组合 |
| 边框 | 1px `--mkt-glass-border` rgba(255,255,255,0.10) | |
| 顶部高光 | `inset 0 1px 0 rgba(255,255,255,0.14)` | 1px「物理边缘受光」，玻璃感的关键一笔；**不外加投影** |
| 模糊 | `backdrop-filter: blur(20px) saturate(140%)` | `@supports not` 降级为实色 `--mkt-bg-elev`（已写入 CSS） |
| 玻璃下的对比度保障 | 卡内文字实测对比均按 `--mkt-bg-elev`（玻璃的最暗可能底）计算并留余量 | 光晕透过来只会更亮，不会更暗 |

**玻璃感的三个来源（缺一不可）**：① 后面真的有东西可透（光晕）；② 1px 亮边框 + 1px 内高光；③ 内容层与背景层之间确有模糊。任何一个缺失，玻璃就变成半透明灰块。

### 4.5 表单字段

- 结构沿用现有 AuthForm / workspace input 规则：**label 在字段上方**（13px `--mkt-fg-2`），永不 placeholder 当 label。
- 字段高 44px（触摸目标），`--mkt-input-bg` + `--mkt-input-border`，`--radius-sm`。
- focus：2px `--mkt-focus-ring` 外扩 2px（`--mkt-focus-ring` = `#4CC9E0`，与暗色主题同一值，两寄存器键盘体验一致）。
- 错误：边框转 `--mkt-danger` + 字段正下方 12px 错误文案（`--mkt-danger`，具体业务原因如「账套号或密码不正确」，禁「出错了」）。三通道规则：错误文案必须带 `CircleAlert` 16px 图标 + 文字，不只红边。
- 登录失败不清空账套号，只清密码——多租户场景账套号是高频输入，保留它。

---

## 5. 文案（全部实词，禁空洞）

| 位置 | 文案 | 为什么这样写 |
|---|---|---|
| 登录主标题 | 你的 AI 员工，刚交了新汇报。 | 面向回访用户的价值确认，动作在标题里（去查看），不是口号 |
| 登录副标题 | 登录后查看每个员工的产出、汇报与成本。 | 三个具体名词：产出/汇报/成本——正是 PRD 定义的产品三交付 |
| 注册主标题 | 雇下第一个 AI 员工。 | PRD 的核心动词「雇」，量词「个」强化员工心智 |
| 注册副标题 | 写好岗位说明书，它今天就上岗。按结果看产出，不按过程烧时间。 | 第一句给出低成本动作，第二句给出 outcome-based 承诺。与 PRD 销售话术同源 |
| 登录 CTA | 登录 | — |
| 注册 CTA | 创建团队 | 「注册」是系统视角，「创建团队」是用户视角 |
| 页脚 | © EvoWork · AI 员工的雇佣与调度平台 | PRD 定位句，非口号 |

禁词继续生效：`Welcome to` / `立即开始体验` / `Seamless` / 虚构指标（「10,000+ 团队的选择」）一律不得出现。页面上**不出现**任何没有数据来源的数字。

---

## 6. 响应式降级策略

| 断点 | 布局 | 降级内容 |
|---|---|---|
| ≥1280px | 完整版 | display-xl 64px + 420px 卡 + WorkbenchPreview 条 |
| 768–1279px | 标题降档 | display-lg 48px；卡与预览不变 |
| 480–767px | 纵向收紧 | display-md 36px；卡 padding 24px；预览条不渲染；导航右侧链接保留 |
| <480px | 最小版 | 标题 32px 行高 40px（局部覆盖 display-md，走 media query 内联值并注释指向本节）；卡 `calc(100vw - 32px)`；副标题 16px/26px |

- 光晕椭圆参数在 <768px 缩小 30%（ellipse 改 `630px 420px` / `490px 350px`），防止小屏上光晕占比过大压住表单。
- 所有断点下表单卡都**完整在首屏内**（`min-height: 100dvh` 用 flex 居中，`scroll` 不应成为登录的必经步骤）。
- 触摸目标全程 ≥44px；页面无横向滚动。

---

## 7. 动效（全页只有一条）

| 动效 | 参数 | 理由 |
|---|---|---|
| 表单卡首次挂载淡入 | opacity 0→1，200ms，`--ease-out`，单元素单属性 | Brand 寄存器允许「一个精心编排的加载时刻」——但只给一个，不给 stagger |

禁令（从 Product 寄存器**全盘继承**）：无入场 stagger、无滚动淡入、无装饰 hover 缩放、无弹跳缓动、背景光晕静态。`prefers-reduced-motion` 由全局规则覆盖（Section 11 已生效）。

---

## 8. 无障碍

- 对比度（按 `--mkt-bg-elev` 最暗底计算）：`fg-1` 13.8:1 AAA / `fg-2` 9.3:1 AAA / `fg-muted` 5.4:1 AA / `nav-fg` 11.2:1 AAA / `cta-fg` 18.9:1 AAA / `danger` 4.9:1 AA。玻璃透光只会提亮背景，对比只升不降。
- 表单错误三通道：红边 + `CircleAlert` 图标 + 具体文案（§4.5）。
- 键盘：Tab 顺序 = 账套号 → 密码 → CTA → 切换链接 → 导航链接。焦点环永不禁用。
- 页面 `<h1>` = 主标题；Segmented Control 用 `role="tablist"` + `aria-selected`；错误文案挂 `aria-live="polite"`。
- 图标全部 lucide-react，strokeWidth 1.5，禁 emoji（P0-1 不豁免）。

---

## 9. 组件状态矩阵（auth 表单）

| 状态 | 表现 |
|---|---|
| Default | 玻璃卡 + 双字段 + 胶囊 CTA |
| Loading | CTA 文案「正在验证…」+ `LoaderCircle` 16px，按钮 disabled，字段保持可读 |
| Error（登录失败） | 字段红边 + `CircleAlert` + 「账套号或密码不正确」；账套号保留 |
| Error（网络失败） | 卡内顶部内联错误条（非 toast）：「连不上服务器，检查网络后重试」+ 重试按钮（`--radius-md` 次级按钮，非胶囊） |
| Empty/Edge | 注册校验沿用现有 AuthForm 逻辑（账套号格式/密码强度提示在字段下方 12px `--mkt-fg-muted`） |
| Success | 登录成功直接跳工作台（现有 redirect 逻辑），**不做**成功庆祝页 |

---

## 10. P0 合规自检

| 红线 | 本方案 |
|---|---|
| P0-1 emoji 图标 | 零 emoji；导航/表单/错误图标均 lucide-react（已验证导出名：`CircleAlert` / `LoaderCircle` 在 §8.7 已验证列表内） |
| P0-2 紫粉渐变 | 光晕色相 210/209/191，物理隔离紫(270°)粉(330°)；无任何 135deg 多色线性渐变 |
| P0-3 AI 模板味 | 文案全部实词（§5）；无空洞 Hero——标题下 48px 就是可操作的表单，Hero 与转化动作零距离 |
| 硬编码颜色 | 全部走 `--mkt-*` token；CSS Section 13 之外零新 hex（primitives 区除外） |
| 弹跳缓动 | 未引入新缓动，复用 `--ease-standard`/`--ease-out` |
| 卡片圆角 ≥24px | 玻璃卡 12px；唯一 pill 是 CTA（有裁定边界） |

---

## 11. 给前端的 3 句话实现要点

1. **画布独立成层**：新建 `.mkt-canvas`（`position:fixed; inset:0; z-index:-1`）承载三层 background（1 垂直亮度渐变 + 2 个 radial 光晕，参数照抄 design-tokens.css Section 13），光晕永不动画；页面根元素挂 `data-marketing="true"`，一切颜色走 `--mkt-*` token，与工作台 token 物理隔离。
2. **玻璃卡三件套**：420px 表单卡 = 半透明渐变底 + 1px 白边框 + `inset 0 1px 0` 顶部高光 + `backdrop-filter: blur(20px) saturate(140%)`，配 `@supports not` 实色降级；卡内沿用现有 AuthForm 结构（label 在上、44px 字段、错误带图标+文案），CTA 用白色胶囊 `.mkt-cta`（48px，`--radius-pill`，loading 态换文案+LoaderCircle）。
3. **标题克制**：主标题 590 字重 + 64/48/36px 三档负字距，颜色 `--mkt-fg-1`，全页唯一动效是卡片 200ms 淡入（opacity 单属性）；`<1024px` 不渲染 WorkbenchPreview，`<768px` 光晕椭圆缩小 30%。
