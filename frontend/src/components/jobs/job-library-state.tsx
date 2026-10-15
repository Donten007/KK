'use client';

import { CircleAlert, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * 岗位库的失败 / 空状态。
 *
 * 两态分开：**加载失败要给重试**，空状态要给具体原因。
 * 合并成一句「暂无数据」是最常见的失职 —— 老板无法区分
 * 「平台还没上架岗位」和「你的网络断了」，行动方式完全不同。
 */
export function JobLibraryState({
  kind,
  message,
  onRetry,
}: {
  kind: 'error' | 'empty';
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="mx-auto w-full max-w-[65ch] px-[var(--space-4)] py-[var(--space-8)]">
      <p
        role={kind === 'error' ? 'alert' : undefined}
        className="flex items-start gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-1)]"
      >
        {kind === 'error' ? (
          <CircleAlert size={20} strokeWidth={1.5} className="mt-[2px] shrink-0 text-[var(--danger)]" aria-hidden="true" />
        ) : null}
        {message}
      </p>

      {kind === 'error' && onRetry ? (
        <div className="mt-[var(--space-4)]">
          <Button variant="secondary" icon={<RefreshCw size={16} strokeWidth={1.5} />} onClick={onRetry}>
            重新加载
          </Button>
        </div>
      ) : null}
    </div>
  );
}