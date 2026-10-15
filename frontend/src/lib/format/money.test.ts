import { describe, expect, it } from 'vitest';
import {
  formatCents,
  formatMinutes,
  formatMonthlyConclusion,
  formatPercent,
  formatRunCostConclusion,
} from '@/lib/format/money';

/**
 * 成本格式化 —— 四舍五入正确性。
 *
 * 分→元是「沉默逻辑错误」高发区（money.ts 顶部注释原话）：
 * 组件里各自做除法会反复出现 18.399999 之类显示错误。
 * 这里的测试锁死统一走 Math.round 的口径，防止后人改回浮点除法。
 */
describe('formatCents（分 → ¥xx.xx）', () => {
  it('整元不带尾零误差', () => {
    expect(formatCents(1840)).toBe('¥18.40');
    expect(formatCents(100)).toBe('¥1.00');
    expect(formatCents(184)).toBe('¥1.84');
    expect(formatCents(1)).toBe('¥0.01');
  });

  it('空值与 NaN 一律归零，不抛错', () => {
    expect(formatCents(null)).toBe('¥0.00');
    expect(formatCents(undefined)).toBe('¥0.00');
    expect(formatCents(Number.NaN)).toBe('¥0.00');
    expect(formatCents(0)).toBe('¥0.00');
  });

  it('半单位四舍五入（Math.round 口径）', () => {
    // 184.5 分 → Math.round(184.5)=185 → 1.85
    expect(formatCents(184.5)).toBe('¥1.85');
    // 184.4 分 → 184 → 1.84（不误进位）
    expect(formatCents(184.4)).toBe('¥1.84');
    // 大额也不漂
    expect(formatCents(999999)).toBe('¥9999.99');
  });
});

describe('formatMonthlyConclusion（约 N 元/月）', () => {
  it('分转元四舍五入到整数元', () => {
    expect(formatMonthlyConclusion(3600)).toBe('约 36 元/月');
    // 3599 分 = 35.99 元 → 四舍五入为 36
    expect(formatMonthlyConclusion(3599)).toBe('约 36 元/月');
    // 3549 分 = 35.49 元 → 35
    expect(formatMonthlyConclusion(3549)).toBe('约 35 元/月');
  });

  it('空值归零', () => {
    expect(formatMonthlyConclusion(null)).toBe('约 0 元/月');
    expect(formatMonthlyConclusion(undefined)).toBe('约 0 元/月');
  });
});

describe('formatRunCostConclusion（单次成本，一位小数）', () => {
  it('保留一位小数', () => {
    expect(formatRunCostConclusion(120)).toBe('1.2 元');
    expect(formatRunCostConclusion(121)).toBe('1.2 元');
    expect(formatRunCostConclusion(125)).toBe('1.3 元');
  });

  it('空值归零', () => {
    expect(formatRunCostConclusion(null)).toBe('0.0 元');
  });
});

describe('formatPercent（整数百分比）', () => {
  it('四舍五入到整数', () => {
    expect(formatPercent(51, 100)).toBe('51%');
    expect(formatPercent(1, 3)).toBe('33%');
    expect(formatPercent(2, 3)).toBe('67%');
  });

  it('分母为零/空时给占位，不做除零', () => {
    expect(formatPercent(10, 0)).toBe('—');
    expect(formatPercent(0, 0)).toBe('—');
  });
});

describe('formatMinutes（分钟 → 小时/分钟）', () => {
  it('边界换算不丢分钟', () => {
    expect(formatMinutes(0)).toBe('0 分钟');
    expect(formatMinutes(40)).toBe('40 分钟');
    expect(formatMinutes(60)).toBe('1 小时');
    expect(formatMinutes(160)).toBe('2 小时 40 分钟');
  });

  it('空值与小数四舍五入', () => {
    expect(formatMinutes(null)).toBe('0 分钟');
    expect(formatMinutes(59.6)).toBe('1 小时');
  });
});
