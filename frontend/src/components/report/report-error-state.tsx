'use client';

import { CircleAlert, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * 加载失败态。
 *
 * 空状态/失败态**必须给具体原因 + 重试**，不写「服务异常」。
 * 「省略比报错更伤信任」：老板看到空白页会以为今天没活干，
 * 而不是"系统出问题了"。二者对他的行动含义完全不同。
 */
export function ReportErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mx-auto flex w-full max-w-[var(--measure-prose)] flex-col gap-[var(--space-4)] px-[var(--space-4)] py-[var(--space-8)]"
    >
      <p className="flex items-start gap-[var(--space-2)] text-[var(--text-md)] text-[var(--fg-1)]">
        <CircleAlert size={20} strokeWidth={1.5} className="mt-[2px] shrink-0 text-[var(--danger)]" aria-hidden="true" />
        {message}
      </p>
      <div>
        <Button variant="secondary" icon={<RefreshCw size={16} strokeWidth={1.5} />} onClick={onRetry}>
          重新加载
        </Button>
      </div>
    </div>
  );
}