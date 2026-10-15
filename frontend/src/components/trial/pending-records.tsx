'use client';

/**
 * 试跑结果页区块 B：干得怎么样（待确认记录）。
 *
 * 每条**必须含「依据」行**（引用具体文件与位置）。这是把
 * 「它不确定」转成「它查过且发现了矛盾」的唯一手段 ——
 * **没有依据行，问问题就等于甩锅**。
 *
 * 视觉纪律（UIUX §8.2）：
 * - 用 `Hand`（举手），不用 TriangleAlert，不用 warn/danger 作容器色
 * - 「跳过」**禁止**做成与「按我这样处理」同等视觉重量 —— 那会暗示跳过是正常路径
 */

import { Hand } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { components } from '@/types/api';

type PendingItem = components['schemas']['PendingItem'];

interface Evidence {
  source?: string;
  detail?: string;
  [key: string]: unknown;
}

export function PendingRecords({ items }: { items: PendingItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-[var(--text-base)] text-[var(--fg-2)]">
        这一趟没有需要你确认的地方，员工自己完成了。
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-[var(--space-4)]">
      {items.map((item, index) => {
        const evidence = (item.evidence ?? []) as Evidence[];
        const options = item.options ?? [];

        return (
          <li
            key={item.id ?? `pending-${index}`}
            className="flex flex-col gap-[var(--space-2)] rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--surface-2)] p-[var(--card-padding)]"
          >
            <p className="flex items-start gap-[var(--space-2)] text-[var(--text-md)] text-[var(--fg-1)]">
              <Hand size={16} strokeWidth={1.5} className="mt-[4px] shrink-0 text-[var(--info)]" aria-hidden="true" />
              <span>{item.reason ?? '有一处我没有把握，想请你确认。'}</span>
            </p>

            {/* 依据行：没有它，问问题就等于甩锅 */}
            {evidence.length > 0 ? (
              <ul className="flex flex-col gap-[var(--space-1)] border-l border-[var(--border)] pl-[var(--space-3)]">
                {evidence.map((ev, evIndex) => (
                  <li key={evIndex} className="text-[var(--text-sm)] text-[var(--fg-2)]">
                    {ev.source ? <span className="text-[var(--fg-1)]">{ev.source}</span> : null}
                    {ev.source && ev.detail ? ' · ' : null}
                    {ev.detail}
                  </li>
                ))}
              </ul>
            ) : null}

            {options.length > 0 ? (
              <div className="flex flex-wrap gap-[var(--space-2)] pt-[var(--space-1)]">
                {options.map((option, optionIndex) => (
                  <Button
                    key={option}
                    size="sm"
                    /* 第一个选项是主路径，用 primary；其余降级。
                       「跳过」不走这里—— 跳过必须有独立且更轻的入口，
                       否则会暗示跳过是正常路径。 */
                    variant={optionIndex === 0 ? 'primary' : 'secondary'}
                    disabled
                    title="待确认队列页在下一阶段开放"
                  >
                    {option}
                  </Button>
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}