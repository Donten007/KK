#!/usr/bin/env bash
# ==========================================================================
# P0 前端门禁 —— 任一项失败即阻断，不允许跳过
# --------------------------------------------------------------------------
# 1. emoji 作功能图标（design-tokens qualityRules.noEmojiAsIcon）
# 2. 组件层裸 hex（qualityRules.noBareHex，唯一例外 #fff / #000）
# 3. 禁止的弹跳缓动（qualityRules.noBounceEasing）
# 4. 禁止的紫色→粉色渐变 / 渐变文字 / 左侧色条 / 卡片圆角 ≥24px
# 5. 单文件 > 300 行（code-organization §4 硬规则）
# 6. 图标名必须在 lucide-react@1.57.0 真实导出中
# ==========================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

FAIL=0
note() { printf '\n=== %s ===\n' "$1"; }
fail() { printf 'BLOCKED: %s\n' "$1"; FAIL=1; }

# --- 1. emoji ---------------------------------------------------------------
# 只匹配真正的 emoji 区段，**排除注释里的箭头 → 与趋势箭头 ↑↓**——
# 后两者是 UIUX §11.1 强制要求的表达，不是图标。
note "1/8 emoji as functional icon"
EMOJI=$(grep -rPl '[\x{1F300}-\x{1F9FF}\x{2600}-\x{27BF}\x{FE0F}\x{1F000}-\x{1F2FF}]' \
  src --include='*.tsx' --include='*.ts' 2>/dev/null | grep -v 'types/api.d.ts')
if [ -n "$EMOJI" ]; then fail "emoji found: $EMOJI"; else echo "PASS"; fi

# --- 2. 裸 hex --------------------------------------------------------------
# 只扫组件/页面层。src/types/api.d.ts 是机器生成物，不受样式门禁约束。
note "2/8 bare hex in component code"
HEX=$(grep -rn '#[0-9a-fA-F]\{3\}\b\|#[0-9a-fA-F]\{6\}\b\|#[0-9a-fA-F]\{8\}\b' \
  src --include='*.tsx' --include='*.ts' 2>/dev/null \
  | grep -v 'types/api.d.ts' \
  | grep -viE '#fff\b|#ffffff\b|#000\b|#000000\b' || true)
if [ -n "$HEX" ]; then printf '%s\n' "$HEX"; fail "bare hex found"; else echo "PASS"; fi

# --- 3. 弹跳缓动 ------------------------------------------------------------
# 排除注释行：文档里为了说明「禁用此值」会原样写出该值，
# 门禁不能有假阳性——一个总报错的门禁等于没有门禁。
note "3/8 forbidden bounce easing"
BOUNCE=$(grep -rn '0\.68.*-0\.55\|0\.265.*1\.55' src 2>/dev/null \
  | grep -vE '^\S+:[0-9]+: *(\*|//|/\*)' || true)
if [ -n "$BOUNCE" ]; then printf '%s\n' "$BOUNCE"; fail "bounce easing found"; else echo "PASS"; fi

# --- 4. AI 模板特征 ---------------------------------------------------------
note "4/8 AI template artifacts"
AI=$(grep -rn 'from-purple-\|to-pink-\|7C3AED\|A855F7\|EC4899\|background-clip:\s*text\|linear-gradient(135deg' \
  src 2>/dev/null || true)
if [ -n "$AI" ]; then printf '%s\n' "$AI"; fail "AI template artifact found"; else echo "PASS"; fi

# 左侧色条：border-left 宽度 > 1px 且带语义色
STRIPE=$(grep -rnE 'border-left-(\[[0-9]+px\]|[234])' src 2>/dev/null || true)
if [ -n "$STRIPE" ]; then printf '%s\n' "$STRIPE"; fail "left color stripe found"; else echo "PASS (left stripe)"; fi

# --- 5. 单文件行数 ----------------------------------------------------------
note "5/8 single file > 300 lines"
OVER=$(find src -name '*.ts' -o -name '*.tsx' | grep -v 'types/api.d.ts' \
  | xargs wc -l 2>/dev/null | sort -rn \
  | awk '$1 > 300 && $2 != "total" {print "  " $0}')
if [ -n "$OVER" ]; then printf '%s\n' "$OVER"; fail "file over 300 lines"; else echo "PASS"; fi

# --- 6. 图标名存在性 --------------------------------------------------------
# 静态解析所有 from 'lucide-react' 的具名导入，逐个核对真实包导出。
# 这是 SPEC「坑 9」的防线：文件存在 ≠ 有 PascalCase 导出。
note "6/8 lucide icon name existence"
node scripts/verify-icons.mjs || fail "icon name check failed"

# --- 7. 纯 BYOK 禁词（任务 C）----------------------------------------------
# 禁词不得出现在**用户可见文案**里。注释中为说明"禁止某词"而引用该词是允许的，
# 所以这里排除注释行 —— 否则门禁会因为自己的说明文档而报错，最终被整体忽略。
note "7/8 BYOK forbidden words in UI copy"
BYOK=$(grep -rn '充值\|余额\|平台额度' src --include='*.tsx' --include='*.ts' 2>/dev/null \
  | grep -v 'types/api.d.ts' \
  | grep -vE ':\s*(\*|//|/\*)' || true)
if [ -n "$BYOK" ]; then printf '%s\n' "$BYOK"; fail "BYOK forbidden word in UI copy"; else echo "PASS"; fi

# --- 8. 汇报/试跑语境禁 Token ------------------------------------------------
# 老板在汇报页看到 Token 会把产品归类为「开发工具」（SPEC §7.4试跑页硬约束）。
# 只扫这三个老板面向的目录 —— 管理员用量页（/settings/usage）本就是技术语境。
note "8/8 'Token' forbidden in owner-facing pages"
TOK=$(grep -rni 'token' src/components/report src/components/trial src/components/jobs \
  --include='*.tsx' 2>/dev/null \
  | grep -vE ':\s*(\*|//|/\*)' || true)
if [ -n "$TOK" ]; then printf '%s\n' "$TOK"; fail "'Token' appears in owner-facing page"; else echo "PASS"; fi

printf '\n===========================\n'
if [ "$FAIL" -eq 0 ]; then
  echo "ALL P0 GATES PASSED"
  exit 0
fi
echo "P0 GATE BLOCKED"
exit 1