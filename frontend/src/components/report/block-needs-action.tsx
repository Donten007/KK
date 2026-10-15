import { Hand } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
 * [需资深] 待确认队列页 `/pending` 不在 Phase 2 范围（放行条件只覆盖
 * 汇报/岗位库/试跑）。此处按钮置 disabled 而非链到不存在的路由 ——
 * 一个点了跳 404 的入口，比一个明确告诉你"还没开放"的按钮伤害更大。
 * Phase 3 上线 /pending 后，把 Button 包进 <Link href="/pending"> 即可。
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

      <Button disabled title="待确认队列将在下一阶段开放">逐件处理</Button>
    </div>
  );
}