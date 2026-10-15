'use client';

/**
 * 板块 ④ 花的钱。
 *
 * ## 必渲染（成本永远存在，即使为 0）
 * 为 0 时写「今天没有产生模型调用费用。」—— 不用「¥0.00」，那是技术写法。
 *
 * ## 纯 BYOK 文案纪律（design-tokens copy.byokConstraint）
 * - 主语必须是**客户自己的模型账单**（"生成这份日报，你的模型账单多了 X 元"），
 *   不是平台账单
 * - **禁止**出现「充值」「余额」「平台额度」
 * - SaaS 订阅费与 API 费用**禁止同区块并列** —— 两笔钱不同付款方，
 *   并列会让人以为平台赚模型费，正好摧毁「我们不赚你模型费的钱」这个承诺
 * - API 预算用 --warn 不用 --danger（预算是卖点不是限制）
 *
 * ## 字体纪律（这一条最容易被做错）
 * 主金额用 **body 20px/510，不用等宽**。
 * 等宽数字 = 账单感 —— 这一段要像同事说的话，不是表格里的单元格。
 * （构成列表里的金额才用 mono，见 cost-breakdown-panel）
 */

import { Coins, HandCoins } from 'lucide-react';
import { CostBreakdownPanel } from './cost-breakdown-panel';
import { EMPTY_COPY, type DailyReport } from './report-copy';
import { formatMinutes, formatMonthlyConclusion, formatRunCostConclusion } from '@/lib/format/money';
import type { components } from '@/types/api';

type CostBlock = NonNullable<DailyReport['block4_cost']>;

export function BlockCost({
  block,
  breakdown,
}: {
  block: CostBlock;
  breakdown: components['schemas']['CostBreakdown'] | null;
}) {
  const today = block.today_cost_cents ?? 0;
  const monthly = block.monthly_forecast_cents ?? 0;
  const savedMinutes = block.saved_minutes_today ?? 0;

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      {today <= 0 ? (
        <p className="flex items-center gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-2)]">
          <Coins size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />
          {EMPTY_COPY.cost}
        </p>
      ) : (
        <div className="flex flex-col gap-[var(--space-1)]">
          {/* 结论句：body 字体 20px/510。等宽数字会让这里变成账单 */}
          <p className="text-[var(--text-lg)] font-[var(--weight-medium)] text-[var(--fg-1)]">
            生成这些产出，你的模型账单多了 {formatRunCostConclusion(today)}。
          </p>
          {/* 老板的决策单位是「月」不是「次」 */}
          <p className="text-[var(--text-base)] text-[var(--fg-2)]">
            按这个节奏，你的一个员工一个月{formatMonthlyConclusion(monthly)}。
          </p>
        </div>
      )}

      {/* 折算人力是这一板块的收尾价值：「省下 2 小时 40 分钟」比「花了 1.2 元」
          更能让老板感知价值。必须来自真实数据，无数据就不显示。 */}
      {savedMinutes > 0 ? (
        <p className="flex items-center gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-2)]">
          <HandCoins size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />
          相当于：今天省下约 {formatMinutes(savedMinutes)}人工
        </p>
      ) : null}

      {/* 下钻终点：同页展开员工维度。密度恒为 4。 */}
      {breakdown ? <CostBreakdownPanel data={breakdown} /> : null}
    </div>
  );
}