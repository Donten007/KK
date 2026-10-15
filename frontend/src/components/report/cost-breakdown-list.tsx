'use client';

/**
 * 成本构成（老板视角的下钻终点）—— **无折叠壳版本**。
 *
 * ## 三条禁止（违反即退回，UIUX §8.1）
 * 1. 禁止出现 token / prompt / response / 模型名 / 单价 / 调用次数 任何一项
 * 2. 禁止下钻到员工以下
 * 3. 禁止跳转到 /settings/usage
 *
 * 为什么第 1 条这么严：老板一旦在汇报页看到 token 数字，
 * 就会把整个产品重新归类为「开发工具」，而我们卖的是「员工」。
 * 归类一旦形成，他对价格的容忍度会骤降 —— 这是认知分类问题，不是文案问题。
 *
 * ## 密度必须恒为 4（不进 7）
 * 防止「成本区块悄悄变回账单」：密度一升、表格一排，账单感立刻回来，
 * 认知分类也就跟着回去了。
 *
 * ## 数字分层（同一区块内的纪律）
 * 结论句用 body 字体（像同事说的话），计量用 mono + tabular-nums 右对齐
 * （老板做的是纵向比对，右对齐 + 等宽让小数点成一条竖线）。
 * 两者不矛盾：结论是给你读的，计量是给你比对的。
 *
 * ## [需资深] 本组件**只渲染后端给的数据，不做任何推算**
 * 趋势与折算人工需要后端提供环比与真实工时字段（CostBreakdown 目前未提供）。
 * 在字段落地前，这里**宁可不显示也不编**：
 * SPEC §8.5 把「无数据时编造」定为 P0 缺陷 —— 信任指标造假等于在信任指标里投毒。
 */

import { Pause } from 'lucide-react';
import { formatCents, formatPercent } from '@/lib/format/money';
import type { components } from '@/types/api';

type CostBreakdown = components['schemas']['CostBreakdown'];
type CostItem = NonNullable<CostBreakdown['items']>[number];

/**
 * @param showHeader 是否渲染「成本构成」小标题。
 *        汇报页由父级自带展开按钮，这里隐藏以免重复；
 *        试跑页的下钻入口与标题同处一块，保留标题更清晰。
 */
export function CostBreakdownList({
  data,
  showHeader = true,
}: {
  data: CostBreakdown;
  showHeader?: boolean;
}) {
  const items = data.items ?? [];
  const total = data.total_cost_cents ?? 0;

  if (items.length === 0) {
    return (
      <p className="text-[var(--text-sm)] text-[var(--muted)]">还没有可以拆分的成本记录。</p>
    );
  }

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      {showHeader ? (
        <h3 className="text-[var(--text-sm)] font-[var(--weight-medium)] text-[var(--fg-1)]">
          成本构成
        </h3>
      ) : null}

      <ul className="flex flex-col gap-[var(--space-3)]">
        {items.map((item, index) => (
          <CostRow key={item.agent_id ?? `cost-${index}`} item={item} total={total} />
        ))}
      </ul>

      <div className="flex items-center justify-between border-t border-[var(--border)] pt-[var(--space-3)]">
        <span className="text-[var(--text-sm)] text-[var(--fg-2)]">本月合计</span>
        <span className="tabular text-[var(--text-base)] font-[var(--weight-medium)] text-[var(--fg-1)]">
          {formatCents(total)}
        </span>
      </div>
    </div>
  );
}

function CostRow({ item, total }: { item: CostItem; total: number }) {
  const cost = item.cost_cents ?? 0;
  const ratio = total > 0 ? cost / total : 0;
  const isZero = cost === 0;

  return (
    <li className="flex flex-col gap-[var(--space-1)]">
      <div className="flex items-baseline justify-between gap-[var(--space-3)]">
        <span className="flex items-center gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-1)]">
          {isZero ? (
            /* 零成本员工必须列出并标注 —— 折叠即隐藏会让老板以为漏了人 */
            <>
              <Pause size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />
              <span className="text-[var(--text-sm)] text-[var(--muted)]">今天没有运行</span>
            </>
          ) : null}
          {item.agent_name ?? '未命名员工'}
        </span>

        <span className="flex shrink-0 items-baseline gap-[var(--space-3)]">
          {/* 计量：mono + tabular + 右对齐，供纵向比对 */}
          <span className="tabular text-[var(--text-sm)] text-[var(--fg-1)]">{formatCents(cost)}</span>
          <span className="tabular w-[48px] text-right text-[var(--text-sm)] text-[var(--fg-2)]">
            {isZero ? '—' : formatPercent(cost, total)}
          </span>
        </span>
      </div>

      {!isZero ? (
        /* 占比条：单色 --accent。禁止饼图（UIUX §12） */
        <div className="h-[2px] w-full bg-[var(--surface-3)]">
          <div
            className="h-full bg-[var(--accent)]"
            style={{ width: `${Math.max(0, Math.min(100, ratio * 100))}%` }}
          />
        </div>
      ) : null}
    </li>
  );
}