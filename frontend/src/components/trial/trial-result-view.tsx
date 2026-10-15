'use client';

/**
 * 试跑结果页 `/jobs/{id}/trial`。
 *
 * ## 密度 4 —— 全产品最松
 * 与任务中心抽屉（密度 7）的本质区别：
 * 抽屉回答「出了什么问题」，面向排查者；本页回答「这员工靠不靠谱」，面向老板。
 * 数字风格因此是 body + 无 Token 字样，语气是员工口吻。
 *
 * ## 三区块顺序（UIUX §8.1）
 * A 干了什么 → B 干得怎么样 → C 花了多少钱
 *
 * ## 页面状态（全部显式，不假装）
 * - 有失败项：失败步骤就地显示，不隐藏、不重试、不假装成功
 * - 全部失败：顶部给具体原因 + 下一步动作，不写「服务异常」
 * - 待确认 ≥3：顶部提示条，用 Hand 不用 TriangleAlert
 */

import { CircleAlert, Hand } from 'lucide-react';
import { useApiResource } from '@/hooks/use-api-resource';
import { TrialStepStream } from '@/components/trial/trial-step-stream';
import { PendingRecords } from '@/components/trial/pending-records';
import { TrialCostConclusion } from '@/components/trial/trial-cost-conclusion';
import { ReportErrorState } from '@/components/report/report-error-state';
import type { components } from '@/types/api';

type GoalDetail = components['schemas']['GoalDetail'];
type TaskStep = components['schemas']['TaskStep'];
type PendingItem = components['schemas']['PendingItem'];
type CostBreakdown = components['schemas']['CostBreakdown'];

export function TrialResultView({ goalId }: { goalId: string }) {
  const goal = useApiResource<GoalDetail>(`/api/v1/goals/${goalId}`);
  const steps = useApiResource<TaskStep[]>(`/api/v1/goals/${goalId}/steps`);
  const pending = useApiResource<PendingItem[]>('/api/v1/pending');
  const breakdown = useApiResource<CostBreakdown>('/api/v1/reports/cost-breakdown');

  if (goal.state.status === 'loading') {
    return (
      <div role="status" aria-live="polite" className="mx-auto max-w-[var(--measure-prose)] px-[var(--space-4)] py-[var(--space-8)]">
        {/*员工口吻的加载态：这是唯一允许"加载中"看起来像在干活的地方 */}
        <p className="flex items-center gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-2)]">
          正在跑这一趟…
        </p>
      </div>
    );
  }

  if (goal.state.status === 'error') {
    return <ReportErrorState message={goal.state.error.message} onRetry={goal.reload} />;
  }

  const data = goal.state.data;
  const stepList = steps.state.status === 'success' ? (steps.state.data ?? []) : [];
  const pendingList = pending.state.status === 'success' ? (pending.state.data ?? []) : [];
  const failedSteps = stepList.filter((s) => s.status === 'failed');

  return (
    <div className="mx-auto flex w-full max-w-[var(--measure-prose)] flex-col gap-[var(--space-section)] px-[var(--space-4)] py-[var(--space-8)]">
      <header className="flex flex-col gap-[var(--space-2)]">
        <h1 className="text-[var(--text-xl)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)] text-[var(--fg-1)]">
          {data?.title ?? '试跑结果'}
        </h1>
        {data ? (
          <p className="tabular text-[var(--text-base)] text-[var(--fg-2)]">
            共 {data.actual_steps ?? stepList.length} 步
          </p>
        ) : null}
      </header>

      {/* 待确认 ≥3：顶部提示条。Hand 不是 TriangleAlert —— 这是协作不是故障 */}
      {pendingList.length >= 3 ? (
        <p className="flex items-center gap-[var(--space-2)] rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] px-[var(--space-3)] py-[var(--space-2)] text-[var(--text-sm)] text-[var(--fg-1)]">
          <Hand size={16} strokeWidth={1.5} className="shrink-0 text-[var(--info)]" aria-hidden="true" />
          有 {pendingList.length} 件事在等你确认，员工已经停下来了。
        </p>
      ) : null}

      {/* 全部失败：顶部给具体原因 + 下一步，不写「服务异常」 */}
      {stepList.length > 0 && failedSteps.length === stepList.length ? (
        <div className="flex flex-col gap-[var(--space-2)] rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] p-[var(--space-4)]">
          <p className="flex items-center gap-[var(--space-2)] text-[var(--text-md)] text-[var(--fg-1)]">
            <CircleAlert size={20} strokeWidth={1.5} className="shrink-0 text-[var(--danger)]" aria-hidden="true" />
            这一趟没能跑完
          </p>
          <p className="text-[var(--text-base)] text-[var(--fg-2)]">
            卡在了第一步。补上需要的授权后可以重跑。
          </p>
        </div>
      ) : null}

      {/* A 干了什么 */}
      <section className="flex flex-col gap-[var(--space-4)]">
        <h2 className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
          干了什么
        </h2>
        {steps.state.status === 'error' ? (
          <p className="text-[var(--text-sm)] text-[var(--danger)]">
            工作记录没有加载出来：{steps.state.error.message}
          </p>
        ) : (
          <TrialStepStream steps={stepList} />
        )}
      </section>

      {/* B 干得怎么样 */}
      <section className="flex flex-col gap-[var(--space-4)] border-t border-[var(--border)] pt-[var(--space-6)]">
        <h2 className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
          干得怎么样
        </h2>
        <PendingRecords items={pendingList} />
      </section>

      {/* C 花了多少钱 —— 嵌入式结论，不做成账单式独立区块 */}
      <section className="border-t border-[var(--border)] pt-[var(--space-6)]">
        <TrialCostConclusion
          goal={data ?? null}
          breakdown={breakdown.state.status === 'success' ? breakdown.state.data : null}
        />
      </section>
    </div>
  );
}