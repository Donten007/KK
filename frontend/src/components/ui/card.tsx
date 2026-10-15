/**
 * 卡片。
 *
 * design-tokens component.card：卡片唯一合法形态 = surface-2 底 + 1px border
 * + 8px 圆角 + **无阴影**。四条禁止：
 *  - 无阴影（阴影只给 popover/modal/toast）
 *  - 无左侧色条（AI 设计特征）
 *  - 无嵌套卡片（用分隔线或背景色区分层级）
 *  - 圆角不得 ≥24px
 */

import type { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ children, className = '', ...rest }: CardProps) {
  return (
    <div
      {...rest}
      className={[
        'rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--surface-2)]',
        'p-[var(--card-padding)]',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  );
}