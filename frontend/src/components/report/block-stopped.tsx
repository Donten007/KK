'use client';

import { CircleCheckBig } from 'lucide-react';
import { resolveStoppedSentence, SMALL_SAMPLE_THRESHOLD, type DailyReport } from './report-copy';

/**
 * 板块 ③ 我停下来过 —— 本产品的信任指标。
 *
 * **无论有无都渲染**。它的价值恰恰在于「没发生」这个事实本身可见。
 * 若只在有值时出现，老板就无法区分「今天没人问我」和
 * 「这个数字加载失败了」—— 这是省略比报错更伤信任的直接后果。
 *
 * ## P0 句式规则（四分支，判据：只声明系统能保证的事，不声明依赖用户行为的事）
 *
 * | 条件 | 主句 |
 * |---|---|
 * | N = 0 | 「今天没有员工打断你。」 |
 * | 0 < N < 5 | 「今天停下来问过 N 次。样本不足，今天不做判断。」 |
 * | N ≥ 5 且有未处理 | 「今天停下来问过 N 次，其中 M 次还在等你。」 |
 * | N ≥ 5 且全部已处理 | 「今天停下来问过 N 次，每次你都做了决定。」 |
 *
 * 「每次你都做了决定」描述的是**用户行为**。只要还有未处理项，
 * 这句话就是假的 —— 产品无权代为声明。所以有未处理时**不保留前半句**。
 *
 * 「它们没有一次是猜的」描述系统行为，系统能保证 —— 但只在**全部已处理**时
 * 才允许说（样本不足时下结论，等于在信任指标里投毒）。
 *
 * 后端已在 TrustSummary.main_sentence 里按规则生成，前端**优先渲染不拼接**
 * （resolveStoppedSentence 只在 message 缺失时兜底，且**不自行编造计数**）。
 */

type StoppedBlock = NonNullable<DailyReport['block3_stopped']>;

export function BlockStopped({ block }: { block: StoppedBlock }) {
  const sentence = resolveStoppedSentence(block);
  const total = block.total_this_month ?? 0;
  const awaiting = block.awaiting_count ?? 0;
  // 样本不足（0 < N < 5）不做判断，视觉上也必须中性 —— 不能用 success 绿
  const isSmallSample = total > 0 && total < SMALL_SAMPLE_THRESHOLD;
  // 全部已处理（N ≥ 5 且无未处理）才是唯一允许 success 绿 + 系统保证声明的场景
  const allResolved = total >= SMALL_SAMPLE_THRESHOLD && awaiting === 0;

  if (!sentence) return null;

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <p className="flex items-start gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-1)]">
        <CircleCheckBig
          size={16}
          strokeWidth={1.5}
          // 未处理项禁止 success 绿（绿色会被读成「一切正常」）；样本不足同样中性
          className={
            awaiting > 0 || isSmallSample
              ? 'mt-[3px] shrink-0 text-[var(--muted)]'
              : 'mt-[3px] shrink-0 text-[var(--success)]'
          }
          aria-hidden="true"
        />
        {sentence}
      </p>

      {/* 系统行为保证可以声明：证据来自 escalation 事件的配对统计，不是猜的。
          仅全部已处理时可说；零/样本不足/有未处理都不渲染这一行。 */}
      {allResolved ? (
        <p className="pl-[24px] text-[var(--text-sm)] text-[var(--fg-2)]">
          它们没有一次是猜的 —— 每个问题都带着查到的东西来问你。
        </p>
      ) : null}
    </div>
  );
}
