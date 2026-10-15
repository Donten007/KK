'use client';

import { CalendarClock } from 'lucide-react';

/**
 * 汇报页头部。
 *
 * 日期只做**展示**（回看 30 天的日期切换器属Phase 3 范围）。
 * 现在不加左右切换箭头 —— 箭头能点但点了没反应，比没有箭头更伤信任。
 */
export function ReportHeader({
  reportDate,
  generatedAt,
}: {
  reportDate?: string;
  generatedAt?: string;
}) {
  return (
    <header className="mb-[var(--space-6)] flex flex-col gap-[var(--space-2)]">
      <h1 className="text-[var(--text-xl)] font-[var(--weight-semibold)] tracking-[var(--tracking-tight)] text-[var(--fg-1)]">
        {formatReportDate(reportDate)}
      </h1>
      {generatedAt ? (
        <p className="tabular flex items-center gap-[var(--space-2)] text-[var(--text-xs)] text-[var(--muted)]">
          <CalendarClock size={16} strokeWidth={1.5} aria-hidden="true" />
          {formatGeneratedAt(generatedAt)}
        </p>
      ) : null}
    </header>
  );
}

/** [需资深] 时区纪律：ISO 日期串按 UTC 解析会在东八区偏移一天。
 * 这里按字符串直接取年月日，不经过 Date 解析，避免跨时区差一天。 */
function formatReportDate(iso?: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  if (!match) return '今天';
  const [, year, month, day] = match;
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`;
}

function formatGeneratedAt(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '';
  const hh = String(parsed.getHours()).padStart(2, '0');
  const mm = String(parsed.getMinutes()).padStart(2, '0');
  return `${hh}:${mm} 更新`;
}