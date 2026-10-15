import Link from 'next/link';
import { Hand } from 'lucide-react';
import { buildNeedsActionBlock, type DailyReport } from './report-copy';

/**
 * 板块 ② 要你管。
 *
 * **本板块为 0 时不渲染**（返回 null）——「一切正常」是噪音，
 * 没有事要管就不该占老板的注意力。这与板块 ③ 的处理**故意相反**。
 *
 * ≥3 条时追加 Hand 图标 + 「员工已经停下来了」，暗示损失。
 *
 * 为什么用 `Hand`（举手）而不是 `TriangleAlert`：
 * 这是本产品**唯一会被「非故障」触发的红/黄场景**。员工停下来问问题是
 * 正确行为，不是出错。UIUX §8.2 原话：用红色会让一个正向设计变成信任负债 ——
 * 老板一旦建立「红色 = 有问题」的映射，以后看到红色就紧张，
 * 而这条队列不是问题，是协作。
 *
 * 因此：不用 --warn / --danger 作容器色，不用告警图标。
 *
 * 「逐件处理」跳到 /pending（Phase 3 上线）。有条目时才是真实入口，
 * 没有条目时本板块根本不渲染 —— 不存在点了跳空的可能。
 */
export function BlockNeedsAction({ block }: { block: DailyReport['block2_needs_action'] }) {
  const needsAction = buildNeedsActionBlock(block);
  // 整个板块不渲染 —— 不是写「一切正常」
  if (!needsAction) return null;

  const { count, agentsStopped } = needsAction;

  return (
    <div className="flex flex-wrap items-center justify-between gap-[var(--space-3)]">
      <div className="flex flex-col gap-[var(--space-1)]">
        <p className="text-[var(--text-md)] text-[var(--fg-1)]">{count} 件事在等你确认</p>
        {count >= 3 && agentsStopped ? (
          <p className="flex items-center gap-[var(--space-2)] text-[var(--text-sm)] text-[var(--fg-2)]">
            <Hand size={16} strokeWidth={1.5} className="text-[var(--info)]" aria-hidden="true" />
            员工已经停下来了。
          </p>
        ) : null}
      </div>

      <Link
        href="/pending"
        className={[
          'inline-flex min-h-[var(--tap-target)] items-center justify-center gap-2 rounded-[var(--btn-radius)] px-4',
          'bg-[var(--accent)] text-[var(--text-sm)] text-[var(--accent-on)]',
          'transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)]',
          'hover:bg-[var(--accent-hover)] active:scale-[var(--press-scale)] active:bg-[var(--accent-press)]',
        ].join(' ')}
      >
        逐件处理
      </Link>
    </div>
  );
}