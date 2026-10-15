'use client';

/**
 * 顶栏：面包屑 · 主题切换 · 登出。
 *
 * 登录墙内的页面**不放**搜索与通知 —— Phase 2 没有全局搜索，
 * 放一个按了没反应的入口等于告诉用户"你买的东西是坏的"。
 */

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Hand, LogOut } from 'lucide-react';
import { ThemeToggle } from './theme-toggle';
import { logout } from '@/lib/api/auth';
import type { components } from '@/types/api';

interface TopbarProps {
  /** 账套号，如 AC-8F3K2M9W。这是客户身份，一码一公司 */
  tenantCode?: string;
  tenantName?: string;
  user?: components['schemas']['User'];
  /** 待确认数量（真实接口数据）。为 0 时不显示角标。 */
  pendingCount?: number;
}

export function Topbar({ tenantCode, tenantName, user, pendingCount = 0 }: TopbarProps) {
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace('/login');
  }

  return (
    <header className="flex h-[var(--topbar-h)] shrink-0 items-center justify-between gap-[var(--space-3)] border-b border-[var(--border)] bg-[var(--surface-1)] px-[var(--space-4)]">
      <div className="flex min-w-0 items-center gap-[var(--space-2)]">
        {tenantName ? (
          <span className="truncate text-[var(--text-sm)] text-[var(--fg-1)]">{tenantName}</span>
        ) : null}
        {/* 账套号：可口述、可报给客服，不是数据库主键 */}
        {tenantCode ? (
          <span className="tabular shrink-0 text-[var(--text-xs)] text-[var(--muted)]">
            {tenantCode}
          </span>
        ) : null}
      </div>

      <div className="flex items-center gap-[var(--space-1)]">
        {/* 待确认入口：真实接口数据，为 0 不显示。Hand = 协作不是故障（UIUX §8.2） */}
        {pendingCount > 0 ? (
          <Link
            href="/pending"
            aria-label={`${pendingCount} 件事等你确认`}
            className={[
              'inline-flex min-h-[var(--tap-target)] items-center gap-[var(--space-1)]',
              'rounded-[var(--radius-sm)] px-[var(--space-2)]',
              'text-[var(--text-sm)] text-[var(--info)]',
              'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
              'hover:bg-[var(--surface-hover)]',
            ].join(' ')}
          >
            <Hand size={16} strokeWidth={1.5} aria-hidden="true" />
            <span>等你确认 {pendingCount}</span>
          </Link>
        ) : null}

        <ThemeToggle />

        {user?.email ? (
          <span className="hidden max-w-[200px] truncate text-[var(--text-sm)] text-[var(--fg-2)] sm:inline">
            {user.email}
          </span>
        ) : null}

        <button
          type="button"
          onClick={handleLogout}
          aria-label="退出登录"
          title="退出登录"
          className={[
            'inline-flex h-[var(--tap-target)] w-[var(--tap-target)] items-center justify-center',
            'rounded-[var(--radius-sm)] text-[var(--fg-2)]',
            'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
            'hover:bg-[var(--surface-hover)] hover:text-[var(--fg-1)]',
            'active:scale-[var(--press-scale)]',
          ].join(' ')}
        >
          <LogOut size={20} strokeWidth={1.5} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}