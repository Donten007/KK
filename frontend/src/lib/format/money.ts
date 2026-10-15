/**
 * 金额格式化。
 *
 * [需资深] 三条纪律来自 UIUX §8.1，任何改动都要重读那一节：
 * 1. 结论句（「约 36 元/月」）用 body 字体，**不得**用 mono —— 等宽数字 = 账单感。
 * 2. 构成列表里的金额用 mono + tabular-nums **右对齐** —— 老板要纵向比对大小。
 * 3. 成本永远用「元」的业务口径，不用「分」的技术口径。
 *
 * 分→元换算是"沉默逻辑错误"高发区：这里统一走 Math.round，
 * 且禁止在各组件里自行做除法（曾多次出现 18.399999 显示问题）。
 */

/** 分 → 「¥18.40」。cent 是整数分，避免浮点累积误差。 */
export function formatCents(cent: number | null | undefined): string {
  if (cent === null || cent === undefined || Number.isNaN(cent)) return '¥0.00';
  const yuan = Math.round(cent) / 100;
  return `¥${yuan.toFixed(2)}`;
}

/**
 * 「约 36 元/月」—— 老板的决策单位是「月」不是「次」。
 * 结论句专用，不带小数（精度在这里是负资产，过度精确会让老板质疑模型估算）。
 */
export function formatMonthlyConclusion(cent: number | null | undefined): string {
  const yuan = Math.round((cent ?? 0) / 100);
  return `约 ${yuan.toLocaleString('zh-CN')} 元/月`;
}

/** 单次成本结论句：「多了 1.2 元」。一位小数即可，这是句子不是账单。 */
export function formatRunCostConclusion(cent: number | null | undefined): string {
  const yuan = (cent ?? 0) / 100;
  return `${yuan.toFixed(1)} 元`;
}

/** 占比：51%。整数即可，比小数更易纵向比对。 */
export function formatPercent(part: number, total: number): string {
  if (!total || total <= 0) return '—';
  return `${Math.round((part / total) * 100)}%`;
}

/** 分钟 → 「2 小时 40 分钟」。成本板块的收尾价值表达，省的是时间不是钱。 */
export function formatMinutes(minutes: number | null | undefined): string {
  const total = Math.max(0, Math.round(minutes ?? 0));
  if (total === 0) return '0 分钟';
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours === 0) return `${mins} 分钟`;
  if (mins === 0) return `${hours} 小时`;
  return `${hours} 小时 ${mins} 分钟`;
}

// [需资深] 趋势格式化（↑/↓/— + 数值）**故意暂不实现**：
// CostBreakdown schema 目前没有环比字段（delta_ratio）。
// UIUX §8.1 允许呈现趋势，但前提是**有真实数据**——
// 在无字段时造一个「持平」出来，就是 SPEC §8.5 定义的 P0 缺陷
// （无数据时编造 = 在信任指标里投毒）。
// 后端补上字段后在此实现，届时直接复用下面的方向判定规则。