'use client';

/**
 * 待确认队列 `/pending`。
 *
 * ## 视觉纪律（UIUX §8.2，本产品唯一「非故障」触发红/黄场景的解法）
 * - 图标用 `Hand`（举手），**禁 TriangleAlert**：员工停下来问是协作不是故障
 * - 容器 `--surface-2` + 1px `--border`，**不用 warn/danger 容器色**
 * - 「跳过」禁止做成与「批准继续」同等视觉重量 —— 那会暗示跳过是正常路径
 *
 * ## 每条必须含「依据」行（SPEC §7.5 硬约束 2）
 * 把「它不确定」转成「它查过且发现了矛盾」的唯一手段。没有依据行，问问题等于甩锅。
 *
 * ## 排序
 * 等最久在前（waiting_days 降序，缺失时用 created_at 推算）。
 */

import { useState } from 'react';
import { Hand } from 'lucide-react';
import { useApiResource } from '@/hooks/use-api-resource';
import { apiRequest } from '@/lib/api/client';
import { Button } from '@/components/ui/button';
import { ReportErrorState } from '@/components/report/report-error-state';
import type { components } from '@/types/api';

type PendingItem = components['schemas']['PendingItem'];

interface Evidence {
  source?: string;
  detail?: string;
  [key: string]: unknown;
}

const DAY_MS = 86_400_000;

/** 等待天数：优先后端 waiting_days，缺失时用 created_at 推算（不编造，只是兜底排序）。 */
function waitingDays(item: PendingItem): number {
  if (typeof item.waiting_days === 'number') return item.waiting_days;
  if (!item.created_at) return 0;
  const delta = Date.now() - new Date(item.created_at).getTime();
  return delta > 0 ? Math.floor(delta / DAY_MS) : 0;
}

/** 等最久在前：waiting_days 降序；同为 0 时按创建时间升序（更早 = 等更久）。 */
function sortByLongestWaiting(items: PendingItem[]): PendingItem[] {
  return [...items].sort((a, b) => {
    const wa = waitingDays(a);
    const wb = waitingDays(b);
    if (wa !== wb) return wb - wa;
    return (a.created_at ?? '').localeCompare(b.created_at ?? '');
  });
}

export function PendingQueue() {
  const { state, reload } = useApiResource<PendingItem[]>('/api/v1/pending');

  if (state.status === 'loading') {
    return (
      <div role="status" aria-live="polite" className="px-[var(--space-4)] py-[var(--space-8)]">
        <p className="text-[var(--text-base)] text-[var(--muted)]">正在读待确认列表…</p>
      </div>
    );
  }

  if (state.status === 'error') {
    return <ReportErrorState message={state.error.message} onRetry={reload} />;
  }

  const items = sortByLongestWaiting(state.data ?? []);

  return (
    <div className="mx-auto flex w-full max-w-[var(--measure-prose)] flex-col gap-[var(--space-6)] px-[var(--space-4)] py-[var(--space-8)]">
      <header className="flex flex-col gap-[var(--space-2)]">
        <h1 className="text-[var(--text-xl)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)] text-[var(--fg-1)]">
          待确认
        </h1>
        <p className="max-w-[65ch] text-[var(--text-base)] text-[var(--fg-2)]">
          员工拿不准的事会停在这里，带着依据等你拍板。你不处理，它就一直等着。
        </p>
      </header>

      {items.length === 0 ? (
        <p className="text-[var(--text-base)] text-[var(--fg-2)]">
          现在没有等你确认的事。员工遇到拿不准的，会带着依据停在这里问你。
        </p>
      ) : (
        <ul className="flex flex-col gap-[var(--space-4)]">
          {items.map((item, index) => (
            <PendingItemCard key={item.id ?? `pending-${index}`} item={item} onResolved={reload} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PendingItemCard({ item, onResolved }: { item: PendingItem; onResolved: () => void }) {
  const [amending, setAmending] = useState(false);
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState<'approve' | 'amend' | 'skip' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const evidence = (item.evidence ?? []) as Evidence[];
  const days = waitingDays(item);
  const suggestions = item.options ?? [];

  async function resolve(action: 'approve' | 'amend' | 'skip', payload?: Record<string, unknown>) {
    if (!item.id) return;
    setSubmitting(action);
    setError(null);
    try {
      await apiRequest(`/api/v1/pending/${item.id}/resolve`, {
        method: 'POST',
        body: payload === undefined ? { action } : { action, payload },
      });
      setAmending(false);
      onResolved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '操作没有成功，请重试。');
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <li className="flex flex-col gap-[var(--space-3)] rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--surface-2)] p-[var(--card-padding)]">
      {/* ① 员工原话 + 等待天数 */}
      <div className="flex items-start justify-between gap-[var(--space-3)]">
        <p className="flex items-start gap-[var(--space-2)] text-[var(--text-md)] text-[var(--fg-1)]">
          <Hand size={16} strokeWidth={1.5} className="mt-[4px] shrink-0 text-[var(--info)]" aria-hidden="true" />
          <span>{item.reason ?? '有一处我没有把握，想请你确认。'}</span>
        </p>
        <span className="shrink-0 rounded-[var(--radius-sm)] bg-[var(--info-bg)] px-[var(--space-2)] py-[2px] text-[var(--text-xs)] text-[var(--info)]">
          {days <= 0 ? '今天' : `等 ${days} 天`}
        </span>
      </div>

      {/* ② 任务名 + 停在哪一步 */}
      {(item.goal_title || item.stopped_step) ? (
        <div className="flex flex-col gap-[var(--space-1)] text-[var(--text-sm)] text-[var(--fg-2)]">
          {item.goal_title ? (
            <p>
              <span className="text-[var(--muted)]">任务：</span>
              {item.goal_title}
            </p>
          ) : null}
          {item.stopped_step ? (
            <p>
              <span className="text-[var(--muted)]">停在：</span>
              {item.stopped_step}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* ③ 依据行 —— 没有它，问问题就等于甩锅 */}
      {evidence.length > 0 ? (
        <ul className="flex flex-col gap-[var(--space-1)] border-l border-[var(--border)] pl-[var(--space-3)]">
          {evidence.map((ev, i) => (
            <li key={i} className="text-[var(--text-sm)] text-[var(--fg-2)]">
              {ev.source ? <span className="text-[var(--fg-1)]">{ev.source}</span> : null}
              {ev.source && ev.detail ? ' · ' : null}
              {ev.detail}
            </li>
          ))}
        </ul>
      ) : null}

      {/* 员工建议（若有）—— 供老板快速采纳 */}
      {suggestions.length > 0 ? (
        <p className="text-[var(--text-sm)] text-[var(--muted)]">员工建议：{suggestions.join('、')}</p>
      ) : null}

      {/* ④ 动作：批准 / 我改 / 跳过。跳过必须最轻 */}
      <div className="flex flex-wrap items-center gap-[var(--space-2)] border-t border-[var(--border)] pt-[var(--space-3)]">
        <Button
          size="sm"
          loading={submitting === 'approve'}
          disabled={submitting !== null}
          onClick={() => void resolve('approve')}
        >
          批准继续
        </Button>

        <Button
          size="sm"
          variant="ghost"
          disabled={submitting !== null}
          aria-expanded={amending}
          onClick={() => {
            setAmending((v) => !v);
            setDraft((prev) => prev || suggestions[0] || '');
          }}
        >
          我改
        </Button>

        <Button
          size="sm"
          variant="ghost"
          loading={submitting === 'skip'}
          disabled={submitting !== null}
          onClick={() => void resolve('skip')}
        >
          跳过
        </Button>
      </div>

      {/* 带修改恢复：参数编辑框。amend 走 /resolve 的 payload（LangGraph Command(resume=...)） */}
      {amending ? (
        <div className="flex flex-col gap-[var(--space-2)]">
          <label htmlFor={`amend-${item.id}`} className="text-[var(--text-sm)] text-[var(--fg-2)]">
            写下修改后的值，员工会按这个继续
          </label>
          <textarea
            id={`amend-${item.id}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            className="rounded-[var(--radius-sm)] border border-[var(--border-input)] bg-[var(--surface-2)] p-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-1)]"
          />
          <div className="flex items-center gap-[var(--space-2)]">
            <Button
              size="sm"
              variant="secondary"
              loading={submitting === 'amend'}
              disabled={submitting !== null || draft.trim() === ''}
              onClick={() => void resolve('amend', { value: draft.trim() })}
            >
              确认修改
            </Button>
            <Button size="sm" variant="ghost" disabled={submitting !== null} onClick={() => setAmending(false)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-[var(--text-sm)] text-[var(--danger)]">
          {error}
        </p>
      ) : null}
    </li>
  );
}
