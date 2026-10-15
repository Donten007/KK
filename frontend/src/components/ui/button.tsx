'use client';

/**
 * 按钮。
 *
 * SPEC §7.5 状态矩阵：Default / Hover / Focus-visible / Active / Disabled / Loading
 * 六态齐全。Active 用 scale(0.98)（design-tokens motion.pressScale），
 * **禁止弹跳缓动**（cubic-bezier(0.68,-0.55,0.265,1.55) 是 P0 禁止项）。
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-[var(--accent)] text-[var(--accent-on)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)]',
  secondary:
    'bg-transparent text-[var(--accent)] border border-[var(--accent)] hover:bg-[var(--accent-bg)] active:bg-[var(--accent-bg)]',
  ghost:
    'bg-transparent text-[var(--fg-1)] hover:bg-[var(--surface-hover)] active:bg-[var(--surface-hover)]',
  danger:
    'bg-[var(--danger)] text-white hover:opacity-90 active:opacity-80',
};

const SIZES: Record<Size, string> = {
  // min-height 走 --tap-target 保证 44px 触摸目标（SPEC §7.4 硬约束）
  sm: 'min-h-[var(--tap-target)] px-3 text-[var(--text-xs)]',
  md: 'min-h-[var(--tap-target)] px-4 text-[var(--text-sm)]',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  disabled,
  className = '',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        'inline-flex items-center justify-center gap-2 rounded-[var(--btn-radius)]',
        'transition-[background-color,color,opacity] duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
        'active:scale-[var(--press-scale)]',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100',
        VARIANTS[variant],
        SIZES[size],
        className,
      ].join(' ')}
    >
      {loading ? <LoaderCircle size={16} strokeWidth={1.5} className="icon-spin" /> : icon}
      {/* Loading 时文案不变 —— 变文案会让用户以为提交了另一个动作 */}
      {children}
    </button>
  );
}