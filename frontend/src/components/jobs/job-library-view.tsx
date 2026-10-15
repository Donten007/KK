'use client';

/**
 * 岗位库页 `/jobs`。
 *
 * Phase 2 只有 1 个岗位（竞品监控日报），因此用**单卡布局**。
 * 特别注意：不写「先雇一个」这类文案 —— 「先/再/还有」暗示后面有别的，
 * Phase 2 没有。SPEC §7.1 的2+1+2 分数网格是多岗位时的布局，
 * 单岗位时用不上，也不该为了对齐网格而造第二张卡。
 *
 * 密度 6（浏览 + 偶尔配置）。
 */

import { useApiResource } from '@/hooks/use-api-resource';
import { JobCard } from '@/components/jobs/job-card';
import { JobLibraryState } from '@/components/jobs/job-library-state';
import type { components } from '@/types/api';

type JobTemplate = components['schemas']['JobTemplate'];

export function JobLibraryView() {
  const { state, reload } = useApiResource<JobTemplate[]>('/api/v1/job-templates');

  if (state.status === 'loading') {
    return (
      <div role="status" aria-live="polite" className="px-[var(--space-4)] py-[var(--space-8)]">
        <p className="text-[var(--text-base)] text-[var(--muted)]">正在读取岗位库…</p>
      </div>
    );
  }

  if (state.status === 'error') {
    return <JobLibraryState kind="error" message={state.error.message} onRetry={reload} />;
  }

  const templates = state.data ?? [];

  if (templates.length === 0) {
    /* 空状态给具体原因，不写「暂无数据」。老板需要知道是"没有岗位"
       还是"加载失败" —— 两者对他的行动含义完全不同。 */
    return (
      <JobLibraryState
        kind="empty"
        message="现在还没有可用的岗位。岗位库由平台统一维护，上架后会出现在这里。"
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1100px] px-[var(--space-4)] py-[var(--space-8)]">
      <header className="mb-[var(--space-6)]">
        <h1 className="text-[var(--text-xl)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)] text-[var(--fg-1)]">
          岗位库
        </h1>
        <p className="mt-[var(--space-2)] max-w-[65ch] text-[var(--text-base)] text-[var(--fg-2)]">
          挑一个岗位，员工会按这个岗位的职责自己接工作、写日报。
        </p>
      </header>

      {/* Phase 2 单岗位：单列即可，不套 2+1+2 分数网格（那是多岗位时的布局） */}
      <div className="flex flex-col gap-[var(--space-4)]">
        {templates.map((template, index) => (
          <JobCard key={template.id ?? `job-${index}`} template={template} />
        ))}
      </div>
    </div>
  );
}