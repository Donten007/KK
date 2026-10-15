'use client';

/**
 * 营销页表单字段（UIUX-marketing §4.5）。
 *
 * 结构与 workspace Field 一致：label 在字段**上方**（13px --mkt-fg-2），
 * 禁止 placeholder 当 label；错误文案紧贴字段下方。
 * 差异只在颜色层：全部走 --mkt-* token，与工作台 Field 物理隔离，互不串味。
 *
 * 错误三通道（§4.5/§8）：红边（.mkt-input[aria-invalid]）+ CircleAlert 16px
 * 图标 + 具体业务文案，不只靠颜色。错误文案挂 aria-live="polite"。
 */

import { useId, type InputHTMLAttributes, type ReactNode } from 'react';
import { CircleAlert } from 'lucide-react';

interface MarketingFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string | null;
  hint?: ReactNode;
}

export function MarketingField({ label, error, hint, className = '', ...rest }: MarketingFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <label htmlFor={id} className="text-[var(--text-sm)] text-[var(--mkt-fg-2)]">
        {label}
      </label>
      <input
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : hint ? hintId : undefined}
        className={[
          'mkt-input w-full px-3 text-[var(--text-base)]',
          'disabled:cursor-not-allowed disabled:opacity-55',
          className,
        ].join(' ')}
      />
      {error ? (
        <p
          id={errorId}
          aria-live="polite"
          className="flex items-center gap-[var(--space-1)] text-[12px] leading-[18px] text-[var(--mkt-danger)]"
        >
          <CircleAlert size={16} strokeWidth={1.5} className="shrink-0" aria-hidden="true" />
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-[12px] leading-[18px] text-[var(--mkt-fg-muted)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
