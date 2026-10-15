'use client';

import { CircleCheckBig } from 'lucide-react';
import { EMPTY_COPY, type DailyReport } from './report-copy';

/**
 * 板块 ③ 我停下来过 —— 本产品的信任指标。
 *
 * **无论有无都渲染**。它的价值恰恰在于「没发生」这个事实本身可见。
 * 若只在有值时出现，老板就无法区分「今天没人问我」和
 * 「这个数字加载失败了」—— 这是省略比报错更伤信任的直接后果。
 *
 * ## P0 句式规则（判据：只声明系统能保证的事，不声明依赖用户行为的事）
 *
 * | 条件 | 主句 |
 * |---|---|
 * | N = 0 | 「今天没有员工打断你。」 |
 * | 有未处理 | 「本周停下来问过 N 次，**其中 M 次还在等你**。」 |
 * | 全部已处理 | 「本周停下来问过 N 次，每次你都做了决定。」 |
 *
 * 「每次你都做了决定」描述的是**用户行为**。只要还有未处理项，
 * 这句话就是假的 —— 产品无权代为声明。所以有未处理时**不保留前半句**。
 *
 * 「它们没有一次是猜的」描述系统行为，系统能保证，可以保留。
 *
 * 后端已在 TrustSummary.main_sentence 里按规则二选一生成，
 * 前端**只渲染不拼接**（SPEC TrustSummary：前端不得自行拼接）。
 */

type StoppedBlock = NonNullable<DailyReport['block3_stopped']>;

/** 后端 message 优先；缺失时用本地规则兜底，但**不自行编造计数**。 */
function resolveSentence(block: StoppedBlock): string | null {
  const message = block.message?.trim();
  if (message) return message;

  const total = block.total_this_month ?? 0;
  if (total <= 0) return EMPTY_COPY.stopped;

  const awaiting = block.awaiting_count ?? 0;
  if (awaiting > 0) return `今天停下来问过 ${total} 次，其中 ${awaiting} 次还在等你。`;
  return `今天停下来问过 ${total} 次，每次你都做了决定。`;
}

export function BlockStopped({ block }: { block: StoppedBlock }) {
  const sentence = resolveSentence(block);
  const awaiting = block.awaiting_count ?? 0;

  if (!sentence) return null;

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <p className="flex items-start gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-1)]">
        <CircleCheckBig
          size={16}
          strokeWidth={1.5}
          // awaiting > 0 时**禁止用 success 绿** —— 绿色会被读成「一切正常」，
          // 而实际上还有事在等老板（design-tokens copy.trustMetric.forbiddenColor）
          className={awaiting > 0 ? 'mt-[3px] shrink-0 text-[var(--muted)]' : 'mt-[3px] shrink-0 text-[var(--success)]'}
          aria-hidden="true"
        />
        {sentence}
      </p>

      {/* 系统行为保证可以声明：证据来自 escalation 事件的配对统计，不是猜的 */}
      {sentence !== EMPTY_COPY.stopped && awaiting === 0 ? (
        <p className="pl-[24px] text-[var(--text-sm)] text-[var(--fg-2)]">
          它们没有一次是猜的 —— 每个问题都带着查到的东西来问你。
        </p>
      ) : null}
    </div>
  );
}