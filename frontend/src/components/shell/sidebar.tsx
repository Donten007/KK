'use client';

/**
 * 侧边导航。
 *
 * SPEC §7.3：240px，折叠 56px（仅图标 20px，aria-label 必填）。
 * 导航项高 36px，圆角 6px，选中态 = surface-2 底 + fg-1 字色，
 * **不用左侧色条**（UIUX §12 禁止清单）。
 * 分组标题按「运营 / 资产 / 账户」三组。
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NAV_GROUPS } from './nav-config';

export function Sidebar() {
  const pathname = usePathname();

  const isActive = (href: string) => (href === '/' ? pathname === '/' : pathname.startsWith(href));

  return (
    <aside
      className="hidden h-dvh w-[var(--sidebar-w)] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-1)] md:flex"
      aria-label="主导航"
    >
      {/* 品牌区：账套号是客户身份，一码一公司 */}
      <div className="flex h-[var(--topbar-h)] items-center px-[var(--space-4)]">
        <span className="text-[var(--text-md)] font-[var(--weight-semibold)] text-[var(--fg-1)]">
          EvoWork
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto px-[var(--space-2)] py-[var(--space-3)]">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-[var(--space-4)]">
            {/* 分组标题：ALL CAPS 必须加字距 0.06em（design-tokens typography.tracking.caps） */}
            <p className="px-[var(--space-2)] pb-[var(--space-2)] text-[var(--text-xs)] uppercase tracking-[var(--tracking-caps)] text-[var(--muted)]">
              {group.title}
            </p>
            <ul className="flex flex-col gap-[var(--space-1)]">
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? 'page' : undefined}
                      className={[
                        'flex min-h-[var(--tap-target)] items-center gap-[var(--space-2)]',
                        'rounded-[var(--radius-sm)] px-[var(--space-2)]',
                        'text-[var(--text-sm)]',
                        'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
                        active
                          ? 'bg-[var(--surface-2)] text-[var(--fg-1)]'
                          : 'text-[var(--fg-2)] hover:bg-[var(--surface-hover)] hover:text-[var(--fg-1)]',
                      ].join(' ')}
                    >
                      <Icon size={20} strokeWidth={1.5} aria-hidden="true" />
                      <span>{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}