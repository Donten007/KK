import type { components } from '@/types/api';

type DailyReport = components['schemas']['DailyReport'];

/**
 * 空状态文案。
 *
 * **四板块的空状态刻意各不相同**，这是产品决定不是偷懒（UIUX §8.5）：
 *
 * | 板块 | 为 0 时 | 为什么 |
 * |---|---|---|
 * | ① 做完了什么 | **不隐藏板块**，写「今天没有需要产出的活，员工在待命」+ Pause | 静默隐藏会让老板怀疑「是不是坏了」 |
 * | ② 要你管 | **整个板块不渲染** | 「一切正常」是噪音 —— 没有事要管，就不该占老板注意力 |
 * | ③ 我停下来过 | **渲染**「今天没有员工打断你。」 | 它的价值恰恰在于「没发生」这个事实本身可见 |
 * | ④ 花的钱 | **必渲染**「今天没有产生模型调用费用。」 | 成本永远存在，即使为 0；写 ¥0.00 是技术写法 |
 *
 * 底层原则：**省略比报错更伤信任。** 老板无法区分「没活干」和「被跳过了」。
 */
export const EMPTY_COPY = {
  /** ① 用中性措辞，不用庆祝或道歉语气 */
  completed: '今天没有需要产出的活，员工在待命。',
  /** ③ 已由 PM 采纳的文案 */
  stopped: '今天没有员工打断你。',
  /** ④ 明确说「没有产生费用」而不是「¥0.00」 */
  cost: '今天没有产生模型调用费用。',
} as const;

/** ② 为 0 时返回 null = 整个板块不渲染（不是写「一切正常」） */
export function buildNeedsActionBlock(block: DailyReport['block2_needs_action']) {
  if (!block) return null;
  const count = block.pending_count ?? 0;
  if (count <= 0) return null;
  return { count, agentsStopped: block.agents_stopped ?? false };
}

type StoppedBlock = NonNullable<DailyReport['block3_stopped']>;

/**
 * 样本不足阈值（design-tokens copy.trustMetric.smallSampleThreshold）。
 * N < 5 时不做红/黄/绿判断 —— 样本不足时下结论是另一种不信任。
 */
export const SMALL_SAMPLE_THRESHOLD = 5;

/**
 * 板块 ③「我停下来过」的信任指标主句 —— 四分支。
 *
 * 后端 TrustSummary.message 优先（前端只渲染不拼接）；缺失时按此规则兜底：
 *
 * | 条件 | 主句 |
 * |---|---|
 * | N = 0 | 「今天没有员工打断你。」 |
 * | 0 < N < 5 | 「今天停下来问过 N 次。样本不足，今天不做判断。」 |
 * | N ≥ 5 且有未处理 | 「今天停下来问过 N 次，其中 M 次还在等你。」 |
 * | N ≥ 5 且全部已处理 | 「今天停下来问过 N 次，每次你都做了决定。」 |
 *
 * 「每次你都做了决定」描述的是**用户行为**——只要有未处理项它就是假的，
 * 产品无权代为声明，所以有未处理时**不保留前半句**。
 * 「样本不足」对应 design-tokens 的 smallSample 分支：数据不够时不做判断。
 */
export function resolveStoppedSentence(block: StoppedBlock): string | null {
  const message = block.message?.trim();
  if (message) return message;

  const total = block.total_this_month ?? 0;
  if (total <= 0) return EMPTY_COPY.stopped;

  const awaiting = block.awaiting_count ?? 0;
  if (total < SMALL_SAMPLE_THRESHOLD) {
    return `今天停下来问过 ${total} 次。样本不足，今天不做判断。`;
  }
  if (awaiting > 0) return `今天停下来问过 ${total} 次，其中 ${awaiting} 次还在等你。`;
  return `今天停下来问过 ${total} 次，每次你都做了决定。`;
}

export type { DailyReport };