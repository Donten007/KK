'use client';

import { Eye, FileSpreadsheet, FileText, Pause } from 'lucide-react';
import { EMPTY_COPY, type DailyReport } from './report-copy';

/**
 * 板块 ① 今天做完了什么。
 *
 * 关键约束：
 * - 按员工分组，组内按产出时间倒序（最新在上）—— 老板最关心刚发生的事
 * - 产出行**必须带图标 + 真实文件名** —— 这是「真的干了」的证据，
 *   只有文字描述时老板无法区分真产出和编造
 * - 0 条时**不隐藏板块**（见 report-copy 的 EMPTY_COPY 说明）
 * - 禁止折叠为 0 条状态
 */

type CompletedBlock = NonNullable<DailyReport['block1_completed']>;

interface OutputItem {
  name?: string;
  kind?: string;
  size_bytes?: number;
  asset_id?: string;
}

interface CompletedItem {
  agent_id?: string;
  agent_name?: string;
  summary?: string;
  outputs?: OutputItem[];
}

/** 文件类型 → 图标。只区分「文档」与「表格」两类，够用且不做过度细分。 */
function OutputIcon({ kind }: { kind?: string }) {
  const isSheet = kind === 'row' || kind === 'report';
  const Icon = isSheet ? FileSpreadsheet : FileText;
  return <Icon size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />;
}

export function BlockCompleted({ block }: { block: CompletedBlock }) {
  const items: CompletedItem[] = block.items ?? [];
  const hasContent = block.has_content ?? items.length > 0;

  // 显式说明 0 条，而不是静默留白
  if (!hasContent || items.length === 0) {
    return (
      <p className="flex items-center gap-[var(--space-2)] text-[var(--text-base)] text-[var(--fg-2)]">
        <Pause size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />
        {EMPTY_COPY.completed}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-[var(--space-4)]">
      {items.map((item, groupIndex) => (
        <div key={item.agent_id ?? `group-${groupIndex}`} className="flex flex-col gap-[var(--space-2)]">
          {/* 组间用留白区分，不用分隔线（UIUX §8.5：区块内条目间无分隔线） */}
          <p className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
            {item.agent_name ?? '未命名员工'}
          </p>

          {item.summary ? (
            <p className="text-[var(--text-base)] text-[var(--fg-2)]">{item.summary}</p>
          ) : null}

          {(item.outputs ?? []).length > 0 ? (
            <ul className="flex flex-col gap-[var(--space-1)]">
              {(item.outputs ?? []).map((output, outputIndex) => (
                <li
                  key={output.asset_id ?? `${item.agent_id}-out-${outputIndex}`}
                  className="flex items-center gap-[var(--space-2)]"
                >
                  <OutputIcon kind={output.kind} />
                  <span className="truncate text-[var(--text-sm)] text-[var(--fg-1)]">
                    {output.name ?? '未命名产出'}
                  </span>
                  <button
                    type="button"
                    aria-label={`查看 ${output.name ?? '产出'}`}
                    className="inline-flex min-h-[var(--tap-target)] items-center gap-1 rounded-[var(--radius-sm)] px-[var(--space-2)] text-[var(--text-sm)] text-[var(--accent)] transition-colors duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:bg-[var(--surface-hover)]"
                  >
                    <Eye size={16} strokeWidth={1.5} aria-hidden="true" />
                    查看
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </div>
  );
}