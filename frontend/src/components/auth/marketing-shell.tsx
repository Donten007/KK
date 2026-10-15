/**
 * 营销页壳（/login 与 /register 共用，UIUX-marketing §2）。
 *
 * 四层结构：导航 / 标题区 / 玻璃表单卡 / 页脚，全部居中。
 * 页面根挂 data-marketing="true"，一切颜色走 --mkt-* token
 * （design-tokens.css Section 13），与工作台 Product 寄存器物理隔离。
 *
 * §2.3 WorkbenchPreview：≥1024px 渲染静态预览条（组件根自带 hidden lg:flex），
 * <1024px 不显示。§3.2 品牌微光斑：每页最多 1 个，中心对齐表单卡，
 * pointer-events: none 已在原语内置；与画布三层光晕分工——层叠做氛围，光斑做聚焦。
 *
 * 光晕任何属性永不动画（§3.3 硬性禁令）。
 */

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Bot } from 'lucide-react';
import { WorkbenchPreview } from './workbench-preview';

interface MarketingShellProps {
  /** 页面主标题（<h1>，带句号的完整陈述句，§5 文案表） */
  headline: string;
  /** 副标题，最多两行（max-width: 32em，§4.1） */
  lead: string;
  /** 导航右侧链接：登录/注册互跳 */
  navLink: { href: '/login' | '/register'; label: string };
  children: ReactNode;
}

export function MarketingShell({ headline, lead, navLink, children }: MarketingShellProps) {
  return (
    <div
      data-marketing="true"
      className="flex min-h-dvh flex-col overflow-x-clip bg-[var(--mkt-bg)] text-[var(--mkt-fg-1)]"
    >
      {/* 背景画布：三层光晕（Section 13 .mkt-canvas），静态，永不动画（§3.3） */}
      <div className="mkt-canvas" aria-hidden="true" />

      {/* 导航（§4.2）：64px 毛玻璃通栏，唯一任务「去对面页」，不加菜单项 */}
      <header className="mkt-glass mkt-nav sticky top-0 z-[var(--z-sticky)] flex h-[var(--mkt-nav-h)] items-center justify-between px-[var(--space-5)] md:px-[var(--space-8)]">
        <Link href="/" className="flex min-h-[44px] items-center gap-[var(--space-2)]">
          <Bot size={24} strokeWidth={1.5} className="text-[var(--mkt-fg-1)]" aria-hidden="true" />
          <span className="text-[var(--text-md)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)]">
            EvoWork
          </span>
        </Link>
        <Link
          href={navLink.href}
          className="flex min-h-[44px] items-center text-[var(--text-base)] text-[var(--mkt-nav-fg)] underline-offset-4 transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:text-[var(--mkt-fg-1)] hover:underline"
        >
          {navLink.label} →
        </Link>
      </header>

      <main className="flex w-full flex-1 flex-col items-center px-[var(--space-4)]">
        {/* 标题→卡 48px 间距（§2.1）；顶部 96px 在矮视口按 10dvh 收缩，
            保证「表单卡完整在首屏内」这一 §6 硬约束优先于名义间距 */}
        <h1 className="mkt-display mt-[min(var(--mkt-hero-top-gap),10dvh)]">{headline}</h1>
        <p className="mkt-lead mt-[var(--space-4)] max-w-[32em]">{lead}</p>

        {/* 表单卡 + 品牌微光斑（§3.2：每页唯一 1 个，中心对齐卡片） */}
        <div className="relative mt-[var(--mkt-headline-card-gap)] flex w-full justify-center">
          <div
            aria-hidden="true"
            className="mkt-glow-blob left-1/2 top-1/2 h-[560px] w-[560px] -translate-x-1/2 -translate-y-1/2"
          />
          <section className="mkt-glass mkt-card-in relative z-[1] w-full max-w-[var(--mkt-card-w)] p-[var(--mkt-card-padding)] max-md:p-[var(--space-6)]">
            {children}
          </section>
        </div>

        {/* 真实工作台预览条（§2.3）：衬底证据，仅 ≥1024px，等宽 720px，
            85% 透明度 + 1px 玻璃边框在 globals.css .mkt-preview 应用 */}
        <div className="mkt-preview mt-[var(--mkt-hero-top-gap)] hidden w-full max-w-[720px] lg:block">
          <WorkbenchPreview />
        </div>
      </main>

      <footer className="pb-[var(--space-8)] pt-[var(--space-16)] text-center">
        <p className="text-[var(--text-base)] text-[var(--mkt-fg-muted)]">
          © EvoWork · AI 员工的雇佣与调度平台
        </p>
      </footer>
    </div>
  );
}
