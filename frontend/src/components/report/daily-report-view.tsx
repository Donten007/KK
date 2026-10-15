'use client';

/**
 * 每日汇报页 `/`（老板每天看的页面）。
 *
 * 密度 4（老板在**读**）。四板块**顺序不可调换** ——
 * 顺序本身承载信息：先看成绩，再看要处理的，再看协作，最后才看钱。
 *
 * 内容宽度 65ch（--measure-prose），区块间距 48px。
 * 这两行是密度 4 的主要来源，不是行距。
 */

import { useApiResource } from '@/hooks/use-api-resource';
import { BlockCompleted } from '@/components/report/block-completed';
import { BlockNeedsAction } from '@/components/report/block-needs-action';
import { BlockStopped } from '@/components/report/block-stopped';
import { BlockCost } from '@/components/report/block-cost';
import { DutySummary } from '@/components/report/duty-summary';
import { ReportSection } from '@/components/report/report-section';
import { ReportHeader } from '@/components/report/report-header';
import { ReportErrorState } from '@/components/report/report-error-state';
import type { components } from '@/types/api';

type DailyReport = components['schemas']['DailyReport'];
type CostBreakdown = components['schemas']['CostBreakdown'];

export function DailyReportView() {
  const report = useApiResource<DailyReport>('/api/v1/reports/daily');
  const breakdown = useApiResource<CostBreakdown>('/api/v1/reports/cost-breakdown');

  if (report.state.status === 'loading') {
    return <ReportLoading />;
  }

  // 加载失败必须显式说明并给重试 —— 静默留白会让老板以为"今天没人干活"
  if (report.state.status === 'error') {
    return <ReportErrorState message={report.state.error.message} onRetry={report.reload} />;
  }

  const data = report.state.data;
  if (!data) return <ReportErrorState message="今天的数据没有加载出来。" onRetry={report.reload} />;

  const block3 = data.block3_stopped;
  const block4 = data.block4_cost;

  return (
    <div className="mx-auto w-full max-w-[var(--measure-prose)] px-[var(--space-4)] py-[var(--space-8)]">
      <ReportHeader reportDate={data.report_date} generatedAt={data.generated_at} />

      {/* 验收标准 10：先声明总数，再列待命姓名+原因 */}
      <div className="mb-[var(--space-section)]">
        <DutySummary
          onDutyCount={data.on_duty_count ?? 0}
          standbyCount={data.standby_count ?? 0}
          agents={data.agents ?? []}
        />
      </div>

      <div className="flex flex-col gap-[var(--space-section)]">
        {/* ① 做完了什么 —— 0 条时不隐藏板块 */}
        <ReportSection index="①" title="今天做完了什么">
          <BlockCompleted block={data.block1_completed ?? { has_content: false, items: [] }} />
        </ReportSection>

        {/* ② 要你管 —— 为 0 时整个板块不渲染 */}
        {data.block2_needs_action ? (
          <ReportSection index="②" title="要你管的">
            <BlockNeedsAction block={data.block2_needs_action} />
          </ReportSection>
        ) : null}

        {/* ③ 我停下来过 —— 无论有无都渲染 */}
        {block3 ? (
          <ReportSection index="③" title="我停下来过">
            <BlockStopped block={block3} />
          </ReportSection>
        ) : null}

        {/* ④ 花的钱 —— 必渲染 */}
        {block4 ? (
          <ReportSection index="④" title="花的钱">
            <BlockCost
              block={block4}
              breakdown={breakdown.state.status === 'success' ? breakdown.state.data : null}
            />
          </ReportSection>
        ) : null}
      </div>
    </div>
  );
}

function ReportLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mx-auto w-full max-w-[var(--measure-prose)] px-[var(--space-4)] py-[var(--space-8)]"
    >
      <p className="text-[var(--text-base)] text-[var(--muted)]">正在读今天的汇报…</p>
    </div>
  );
}