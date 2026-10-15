'use client';

/**
 * 主题切换按钮。
 *
 * 深色为默认（暗色原生），浅色是一等公民 —— 所以切换器是常驻的，
 * 不是藏在设置深处。切换结果持久化到 localStorage，优先级高于系统偏好
 * （SPEC §7.2 锁定）。
 *
 * 图标名 Moon / Sun 已核 lucide-react@1.57.0 真实导出。
 */

import { Moon, Sun } from 'lucide-react';
import { useTheme } from '@/hooks/use-theme';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const nextLabel = theme === 'dark' ? '切换到浅色主题' : '切换到深色主题';

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={nextLabel}
      title={nextLabel}
      className={[
        'inline-flex h-[var(--tap-target)] w-[var(--tap-target)] items-center justify-center',
        'rounded-[var(--radius-sm)] text-[var(--fg-2)]',
        'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
        'hover:bg-[var(--surface-hover)] hover:text-[var(--fg-1)]',
        'active:scale-[var(--press-scale)]',
      ].join(' ')}
    >
      {theme === 'dark' ? (
        <Moon size={20} strokeWidth={1.5} aria-hidden="true" />
      ) : (
        <Sun size={20} strokeWidth={1.5} aria-hidden="true" />
      )}
    </button>
  );
}