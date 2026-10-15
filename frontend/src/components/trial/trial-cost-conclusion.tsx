'use client';

/**
 * 试跑成本结论 —— **不是独立区块**。
 *
 * ## 为什么不做成独立区块（UIUX §8.1）
 * 账单 = 表格 + 右对齐数字 + 标签列。成本结论 = 一个句子。
 * PM 的顾虑完全正确：成本区块一旦独立成块，老板第一屏看到明细，
 * 会觉得这东西是给工程师用的。
 *
 * ## 三条具体手法
 * 1. 不用表格
 * 2. **金额用 body 20px/510，不用等宽** —— 等宽数字 = 账单感，
 *    金额要像句子里的词，不像表格里的单元格
 * 3. 主数字是「单次成本 + 推算月度成本」—— 老板的决策单位是「月」不是「次」
 * 4. 明细收进二级入口（同页下钻，不跳页）
 * 5. 金额不加粗放大，最大 20px —— Hero 数字是广告页做法，这是报表页做法
 *
 * ## 纯 BYOK 文案
 * 主语必须是**客户自己的模型账单**，不是平台账单。
 * 禁止「充值」「余额」「平台额度」。
 */

import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { CostBreakdownList } from '@/components/report/cost-breakdown-list';
import { formatMonthlyConclusion, formatRunCostConclusion } from '@/lib/format/money';
import type { components } from '@/types/api';

type Goal = components['schemas']['Goal'];
type CostBreakdown = components['schemas']['CostBreakdown'];

export function TrialCostConclusion({
  goal,
  breakdown,
}: {
  goal: Goal | null;
  breakdown: CostBreakdown | null;
}) {
  const [expanded, setExpanded] = useState(false);

  // 无成本数据时**显式说明**，不显示 ¥0.00，也不编月度推算
  const actual = goal?.actual_cost_cents ?? null;
  const estimated = goal?.estimated_cost_cents ?? null;

  if (actual === null) {
    return (
      <div className="flex flex-col gap-[var(--space-2)]">
        <h2 className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
          这一趟试跑的成本
        </h2>
        <p className="text-[var(--text-base)] text-[var(--fg-2)]">
          这一趟没有产生模型调用费用。
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      <h2 className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
        这一趟试跑的成本
      </h2>

      <p className="text-[var(--text-lg)] font-[var(--weight-medium)] text-[var(--fg-1)]">
        生成这份产出，你的模型账单多了 {formatRunCostConclusion(actual)}。
      </p>

      {/* 月度推算：只在有估算值时说，且标明是估算 —— 预估冒充精确报价是 SPEC 坑 13 */}
      {estimated !== null ? (
        <p className="text-[var(--text-base)] text-[var(--fg-2)]">
          按试跑估算，一个月大约{formatMonthlyConclusion(estimated)}。
        </p>
      ) : null}

      {breakdown ? (
        <>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="inline-flex min-h-[var(--tap-target)] w-fit items-center gap-[var(--space-1)] rounded-[var(--radius-sm)] px-[var(--space-2)] text-[var(--text-sm)] text-[var(--accent)] transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:bg-[var(--surface-hover)]"
          >
            {expanded ? '收起成本明细' : '查看成本明细'}
            <ChevronDown
              size={16}
              strokeWidth={1.5}
              aria-hidden="true"
              className={`transition-transform duration-[var(--motion-fast)] ease-[var(--ease-standard)] ${expanded ? 'rotate-180' : ''}`}
            />
          </button>
          {expanded ? <CostBreakdownList data={breakdown} showHeader={false} /> : null}
        </>
      ) : null}
    </div>
  );
}