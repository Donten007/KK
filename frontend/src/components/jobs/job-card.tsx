'use client';

import { createElement } from 'react';
import * as Lucide from 'lucide-react';
import { CircleCheck, LockKeyhole } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { components } from '@/types/api';

type JobTemplate = components['schemas']['JobTemplate'];

/**
 * 岗位卡片。
 *
 * ## 五要素视觉权重顺序（C8 裁决，UIUX §8.3）
 * 图标 > 岗位名 > 一句话职责 > **交付物** > 上岗前置条件
 *
 * ## 难度递进必须由视觉承载（UIUX §8.3）
 * 难度只存在于产品经理脑子里等于不存在 —— 老板看不出哪个更难，
 * 递进就白设计了。三档用边框与内边距表达：
 *
 * | 难度 | 视觉 |
 * |---|---|
 * | 低 | 24px 图标 + accent 1px 边框 + 略高内边距 |
 * | 中 | 20px 图标 + border 边框 |
 * | 高 | 20px 图标 + border + **border-strong 顶边**（最轻但最清楚） |
 *
 * ## 高难度卡片禁止置灰或降透明度
 * 置灰暗示「不可用」，但它们是真实可用的，只是需先配置。
 * **用边框粗细表达「需要留意」，不用透明度表达。**
 */

const DIFFICULTY = {
  low: {
    iconSize: 24,
    borderClass: 'border-[var(--accent)]',
    paddingClass: 'p-[var(--space-5)]',
  },
  medium: {
    iconSize: 20,
    borderClass: 'border-[var(--border)]',
    paddingClass: 'p-[var(--card-padding)]',
  },
  high: {
    iconSize: 20,
    // 最轻但最清楚：普通边框 + 一条 border-strong 顶边
    borderClass: 'border-[var(--border)] border-t-2 border-t-[var(--border-strong)]',
    paddingClass: 'p-[var(--card-padding)]',
  },
} as const;

/**
 * 岗位图标：取后端下发的 `icon` 字段（lucide-react 图标名）。
 *
 * [需资深] 用运行时查表而不是静态 import —— 后端可下发任意图标名，
 * 静态 import 只能编译期确定的名字。查表 + 显式兜底，
 * 保证「后端下发了一个不存在的名字」时是降级而不是白屏。
 * 降级到 Briefcase 而不是报错：卡片少个图标不影响老板判断。
 */
function resolveJobIcon(name?: string): LucideIcon {
  if (!name) return Lucide.Briefcase;
  const candidate = (Lucide as unknown as Record<string, unknown>)[name];
  return typeof candidate === 'function' || typeof candidate === 'object'
    ? (candidate as LucideIcon)
    : (Lucide.Briefcase as LucideIcon);
}

export function JobCard({ template }: { template: JobTemplate }) {
  const difficulty = template.difficulty ?? 'medium';
  const style = DIFFICULTY[difficulty] ?? DIFFICULTY.medium;

  const prerequisites = template.prerequisites ?? [];
  const deliverables = template.deliverables ?? [];

  return (
    <article
      className={[
        'flex flex-col gap-[var(--space-4)] rounded-[var(--card-radius)] bg-[var(--surface-2)]',
        style.borderClass,
        style.paddingClass,
      ].join(' ')}
    >
      <div className="flex items-start gap-[var(--space-3)]">
        {/* createElement 而非 <Icon />：查表得到的组件类型每次渲染都是新引用，
            用 JSX 写法会让 React 认为组件类型变了而整棵子树重挂载 */}
        {createElement(resolveJobIcon(template.icon), {
          size: style.iconSize,
          strokeWidth: 1.5,
          className: 'shrink-0 text-[var(--fg-2)]',
          'aria-hidden': true,
        })}
        <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <h2 className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
            {template.name ?? '未命名岗位'}
          </h2>
          {template.summary ? (
            <p className="text-[var(--text-base)] text-[var(--fg-2)]">{template.summary}</p>
          ) : null}
        </div>
      </div>

      {/* 交付物：老板真正关心的「它到底交什么」 */}
      {deliverables.length > 0 ? (
        <div className="flex flex-col gap-[var(--space-1)]">
          <p className="text-[var(--text-xs)] uppercase tracking-[var(--tracking-caps)] text-[var(--muted)]">
            交付物
          </p>
          <ul className="flex flex-col gap-[var(--space-1)]">
            {deliverables.map((item) => (
              <li key={item} className="text-[var(--text-sm)] text-[var(--fg-2)]">
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* 上岗前置条件：难度递进的最轻一档也必须说清要做什么 */}
      {prerequisites.length > 0 ? (
        <div className="flex items-start gap-[var(--space-2)]">
          <LockKeyhole size={16} strokeWidth={1.5} className="mt-[2px] shrink-0 text-[var(--muted)]" aria-hidden="true" />
          <p className="text-[var(--text-sm)] text-[var(--fg-2)]">
            {/* 明确计数：高难度档要求「需完成 N 项授权：X、Y」 */}
            {prerequisites.length === 1
              ? `需完成 1 项授权：${prerequisites.join('、')}`
              : `需完成 ${prerequisites.length} 项授权：${prerequisites.join('、')}`}
          </p>
        </div>
      ) : (
        /* 低难度档唯一允许用success 色的地方（UIUX §8.3） */
        <p className="flex items-center gap-[var(--space-2)] text-[var(--text-sm)] text-[var(--success)]">
          <CircleCheck size={16} strokeWidth={1.5} aria-hidden="true" />
          无需配置
        </p>
      )}
    </article>
  );
}