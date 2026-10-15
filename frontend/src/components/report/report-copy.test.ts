import { describe, expect, it } from 'vitest';
import { EMPTY_COPY, resolveStoppedSentence, SMALL_SAMPLE_THRESHOLD } from '@/components/report/report-copy';

/**
 * 信任指标句式 —— 四分支。
 *
 * 判据（design-tokens copy.trustMetric）：只声明系统能保证的事，
 * 不声明依赖用户行为的事。样本不足（N < 5）不下判断。
 */
describe('resolveStoppedSentence（信任指标四分支）', () => {
  it('分支一 · N=0 → 今天没有员工打断你', () => {
    expect(resolveStoppedSentence({ total_this_month: 0 })).toBe(EMPTY_COPY.stopped);
    // total 缺失也按 0 处理
    expect(resolveStoppedSentence({})).toBe(EMPTY_COPY.stopped);
  });

  it('分支二 · 0 < N < 5 → 样本不足，不做判断', () => {
    expect(resolveStoppedSentence({ total_this_month: 3, awaiting_count: 0 })).toBe(
      '今天停下来问过 3 次。样本不足，今天不做判断。',
    );
    expect(resolveStoppedSentence({ total_this_month: 4, awaiting_count: 2 })).toBe(
      '今天停下来问过 4 次。样本不足，今天不做判断。',
    );
  });

  it('分支三 · N ≥ 5 且有未处理 → 其中 M 次还在等你（不保留「你做了决定」）', () => {
    const sentence = resolveStoppedSentence({ total_this_month: 8, awaiting_count: 3 });
    expect(sentence).toBe('今天停下来问过 8 次，其中 3 次还在等你。');
    // 关键判据：有未处理时不得出现「每次你都做了决定」
    expect(sentence).not.toContain('做了决定');
  });

  it('分支四 · N ≥ 5 且全部已处理 → 每次你都做了决定', () => {
    expect(
      resolveStoppedSentence({
        total_this_month: SMALL_SAMPLE_THRESHOLD,
        awaiting_count: 0,
      }),
    ).toBe(`今天停下来问过 ${SMALL_SAMPLE_THRESHOLD} 次，每次你都做了决定。`);
  });

  it('后端 message 优先 —— 前端只渲染不拼接', () => {
    const backend = '本周停下来问过 8 次，其中 3 次还在等你。';
    expect(
      resolveStoppedSentence({ message: backend, total_this_month: 8, awaiting_count: 3 }),
    ).toBe(backend);
  });
});
