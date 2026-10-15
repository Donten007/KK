'use client';

/**
 * 岗位库页 `/jobs`。
 *
 * ## 卡片数 = 已上线岗位数（禁「先雇一个」式暗示）
 * 只有已上线的岗位出现在这里。没上线的岗位**不占位** ——
 * 放一张「敬请期待」卡，老板分不清「功能没做」和「坏了」。
 *
 * ## 布局：2+1+2 分数网格（SPEC §7.5）
 * `grid-template-columns: 1fr 1fr`，首卡跨 2 列（视觉最重）。
 * 难度递进由边框/内边距承载（见 job-card.tsx），不由透明度表达。
 *
 * 密度 6（浏览 + 偶尔配置）。
 *
 * 数据源：后端 `/api/v1/job-templates` 优先；端点未就绪时用 JOB_CATALOG 兜底
 * （岗位是平台级静态内容，不是租户数据，见 lib/jobs/catalog.ts）。
 */

import { useApiResource } from '@/hooks/use-api-resource';
import { JobCard } from '@/components/jobs/job-card';
import { JobLibraryState } from '@/components/jobs/job-library-state';
import { JOB_CATALOG } from '@/lib/jobs/catalog';
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

  // 后端端点就绪后返回真实列表；未就绪时用平台目录兜底（不渲染假数据）。
  const apiTemplates = state.data ?? [];
  const templates = apiTemplates.length > 0 ? apiTemplates : JOB_CATALOG;

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

      {/* 2+1+2 分数网格：首卡跨 2 列（视觉最重），其余 1fr 1fr */}
      <div className="grid grid-cols-1 gap-[var(--space-4)] md:grid-cols-2">
        {templates.map((template, index) => (
          <div key={template.id ?? `job-${index}`} className={index === 0 ? 'md:col-span-2' : undefined}>
            <JobCard template={template} />
          </div>
        ))}
      </div>
    </div>
  );
}
