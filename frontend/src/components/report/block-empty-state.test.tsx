import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BlockCompleted } from '@/components/report/block-completed';
import { BlockNeedsAction } from '@/components/report/block-needs-action';
import { BlockStopped } from '@/components/report/block-stopped';
import { BlockCost } from '@/components/report/block-cost';

/**
 * 日报四板块空状态渲染。
 *
 * 四板块的空状态规则刻意各不相同（UIUX §8.5 / SPEC DailyReport 描述）：
 * ① 不隐藏，写「员工在待命」；② 整个不渲染；③ 必渲染「没有打断你」；④ 必渲染「没有产生费用」。
 * 省略比报错更伤信任 —— 老板必须能区分「没活干」和「被跳过了」。
 */
describe('日报四板块空状态', () => {
  it('① 做完了什么：0 条不隐藏，写「员工在待命」', () => {
    render(<BlockCompleted block={{ has_content: false, items: [] }} />);
    expect(screen.getByText('今天没有需要产出的活，员工在待命。')).toBeInTheDocument();
  });

  it('② 要你管：为 0 时整个板块不渲染（不是写「一切正常」）', () => {
    const { container } = render(
      <BlockNeedsAction block={{ pending_count: 0, agents_stopped: false }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('③ 我停下来过：为 0 时必渲染「今天没有员工打断你」', () => {
    render(<BlockStopped block={{ total_this_month: 0 }} />);
    expect(screen.getByText('今天没有员工打断你。')).toBeInTheDocument();
  });

  it('④ 花的钱：为 0 时必渲染「没有产生模型调用费用」而非 ¥0.00', () => {
    render(
      <BlockCost
        block={{ today_cost_cents: 0, monthly_forecast_cents: 0, saved_minutes_today: 0 }}
        breakdown={null}
      />,
    );
    expect(screen.getByText('今天没有产生模型调用费用。')).toBeInTheDocument();
    expect(screen.queryByText('¥0.00')).not.toBeInTheDocument();
  });
});
