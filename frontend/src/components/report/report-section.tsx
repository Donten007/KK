import type { ReactNode } from 'react';

/**
 * 汇报页板块容器。
 *
 * 密度 4 的主要来源不是行距，而是 **48px 的区块间距**
 * （design-tokens layout → --space-section）。老板在「读」，不是在「扫」。
 *
 * 内容宽度 65ch（--measure-prose，约 720px）—— 保证每行 50–75 字符，
 * 超过这个宽度老板的眼睛会跳行，长段落就读不下去了。
 */
export function ReportSection({
  index,
  title,
  meta,
  children,
}: {
  /** 板块序号 ①–④。渲染出来是流程的一部分，不是装饰 */
  index: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`block-${index}`}
      className="border-t border-[var(--border)] pt-[var(--space-6)] first:border-t-0 first:pt-0"
    >
      <div className="mb-[var(--space-4)] flex flex-wrap items-baseline justify-between gap-[var(--space-2)]">
        <h2
          id={`block-${index}`}
          className="flex items-baseline gap-[var(--space-2)] text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]"
        >
          {/* 序号承载信息（顺序本身有意义），用 muted 弱化，不抢标题 */}
          <span aria-hidden="true" className="text-[var(--text-sm)] text-[var(--muted)]">
            {index}
          </span>
          {title}
        </h2>
        {meta}
      </div>
      <div className="flex flex-col gap-[var(--space-4)]">{children}</div>
    </section>
  );
}