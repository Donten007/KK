'use client';

/**
 * 移动端底部 TabBar。
 *
 * SPEC §7.3：xs <640 时 Sidebar 变底部 TabBar。工作记忆放不下 6 项，
 * 移动端只留最高频的 2 项 + 「更多」，其余页面靠 Phase 3 的抽屉补齐。
 *
 * 触摸目标 ≥44px 是硬约束（WCAG 2.5.5），所以每项给足高度与间距。
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NAV_GROUPS } from './nav-config';

export function MobileTabBar() {
  const pathname = usePathname();
  const items = NAV_GROUPS.flatMap((g) => g.items);

  return (
    <nav
      aria-label="主导航（移动端）"
      className="flex shrink-0 border-t border-[var(--border)] bg-[var(--surface-1)] md:hidden"
    >
      {items.map((item) => {
        const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? 'page' : undefined}
            className="flex min-h-[var(--tap-target)] flex-1 flex-col items-center justify-center gap-[2px] px-[var(--space-2)] py-[var(--space-1)] text-[var(--text-xs)] transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]"
            style={{ color: active ? 'var(--fg-1)' : 'var(--fg-2)' }}
          >
            <Icon size={20} strokeWidth={1.5} aria-hidden="true" />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}