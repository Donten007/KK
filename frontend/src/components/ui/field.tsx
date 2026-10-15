'use client';

/**
 * 表单字段。
 *
 * SPEC §7.5 / design-tokens component.input：
 * label 在字段**上方**（--fg-2 13px），**禁止用 placeholder 当 label** ——
 * 老板不是技术用户，占位符一消失就不知道这个框要填什么。
 */

import { useId, type InputHTMLAttributes, type ReactNode } from 'react';

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string | null;
  hint?: ReactNode;
}

export function Field({ label, error, hint, className = '', ...rest }: FieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <label htmlFor={id} className="text-[var(--text-sm)] text-[var(--fg-2)]">
        {label}
      </label>
      <input
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : hint ? hintId : undefined}
        className={[
          'h-[var(--control-h)] rounded-[var(--input-radius)] px-3',
          'bg-[var(--surface-2)] text-[var(--fg-1)] text-[var(--text-base)]',
          'border transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
          'placeholder:text-[var(--muted)]',
          'disabled:opacity-55 disabled:cursor-not-allowed',
          error
            ? 'border-[var(--danger)]'
            : 'border-[var(--border-input)] hover:border-[var(--border-strong)]',
          className,
        ].join(' ')}
      />
      {/* 错误文案紧贴字段下方（近字段原则），不放到页尾 */}
      {error ? (
        <p id={errorId} className="text-[var(--text-xs)] text-[var(--danger)]">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-[var(--text-xs)] text-[var(--muted)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}