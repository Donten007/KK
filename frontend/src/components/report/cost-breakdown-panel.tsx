'use client';

/**
 * 成本下钻（同页展开容器）。
 *
 * 两层下钻，到此为止：
 * 1. 「约 36 元/月」一句话 —— 老板的决策单位
 * 2. 同页展开「成本构成」—— 员工维度
 *
 * **第 3 层（token 级）已被设计师裁掉，从未进入 Spec。**
 * 理由（UIUX §8.1终裁版）：如果「查看成本明细」把人送去 token 级页面，
 * 等于在自己产品里开了一条绕过自己硬约束的后门 —— 而且是看起来很专业的绕过。
 * 老板看到「36 元」时想知道的是「这钱花得值不值、该砍谁」，
 * 给他一个他不需要的技术答案，比不给更糟。
 *
 * 主动寻路与被动推送是两件事：他若自己走去/settings/usage 是他的选择，
 * 产品替他做决定才是问题。所以这里**不跳页**。
 */

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { CostBreakdownList } from './cost-breakdown-list';
import type { components } from '@/types/api';

type CostBreakdown = components['schemas']['CostBreakdown'];

export function CostBreakdownPanel({ data }: { data: CostBreakdown }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
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

      {/* 同页展开，不跳页 —— 不跳页 = 不进入技术语境，回归是「收起」而非「返回」 */}
      {expanded ? <CostBreakdownList data={data} /> : null}
    </div>
  );
}