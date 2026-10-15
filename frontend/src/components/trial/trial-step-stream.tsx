'use client';

/**
 * 区块 A：干了什么（业务语言步骤流水）。
 *
 * ## 核心决策：员工工作日志的语法，不是系统日志的语法（UIUX §8.1）
 *
 * | 系统日志（禁止） | 员工日志（采用） |
 * |---|---|
 * | `14:32:05 [INFO] search_knowledge(...) → 12 results (1.4s)` | `14:32  查了「2026Q3渠道台账」，找到 12 条相关记录` |
 * | `tool_call: spreadsheet_write(...) success` | `把结果整理进了「竞品日报-0912.xlsx」` |
 * | `[done] elapsed=8m23s tokens=14,208` | `这一趟花了 8 分 23 秒` |
 *
 * ## 三条硬约束
 * 1. **禁止出现「Token」字样**。老板看到 Token 会把产品重新归类为「开发工具」，
 *    而我们卖的是「员工」—— 这是认知分类问题，不是文案问题。
 * 2. **禁止系统日志语汇**（[INFO] / elapsed= / tool_call:）。
 * 3. **不用等宽字体**。等宽是技术感的最大来源，业务日志用 --font-body。
 *
 * ## 密度 4 的来源
 * 行高 32px 且行间**无分隔线**，仅靠行距分组；每段之间空 16px。
 * 行距宽松才是密度 4 的主要来源，不是行距本身。
 *
 * ## 失败步骤不隐藏、不重试、不假装成功
 * 就地显示 CircleX + 业务语言原因 + 「补上授权后重跑」。
 */

import { CircleX, LoaderCircle } from 'lucide-react';
import type { components } from '@/types/api';

type TaskStep = components['schemas']['TaskStep'];

const STATUS_TEXT: Record<string, string> = {
  pending: '还没开始',
  running: '正在做',
  succeeded: '做完了',
  failed: '没做成',
  skipped: '跳过了',
};

export function TrialStepStream({ steps }: { steps: TaskStep[] }) {
  if (steps.length === 0) {
    return (
      <p className="text-[var(--text-base)] text-[var(--fg-2)]">
        这一趟还没有留下工作记录。
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-[var(--space-4)]">
      {steps.map((step, index) => (
        <li key={step.step_ordinal ?? index} className="flex flex-col gap-[var(--space-1)]">
          <div className="flex items-baseline gap-[var(--space-3)]">
            {/* 时间用 mono + tabular（需要纵向对齐），正文用 body */}
            <span className="tabular shrink-0 text-[var(--text-xs)] text-[var(--muted)]">
              {formatStepTime(step.started_at, step.step_ordinal)}
            </span>
            <span className="text-[var(--text-base)] text-[var(--fg-1)]">
              {step.title ?? '未命名步骤'}
            </span>
          </div>

          <div className="flex items-center gap-[var(--space-2)] pl-0">
            <StepStatusLine status={step.status} errorCode={step.error_code} />
          </div>
        </li>
      ))}
    </ol>
  );
}

function StepStatusLine({ status, errorCode }: { status?: string; errorCode?: string | null }) {
  if (status === 'running') {
    return (
      <p className="flex items-center gap-[var(--space-2)] text-[var(--text-sm)] text-[var(--accent)]">
        <LoaderCircle size={16} strokeWidth={1.5} className="icon-spin" aria-hidden="true" />
        {STATUS_TEXT.running}
      </p>
    );
  }

  if (status === 'failed') {
    /* 失败必须说清原因，且用业务语言。
       SPEC copy.noSystemBehaviorLeak：熔断文案只讲业务事实，
       不暴露检测阈值或内部机制。 */
    return (
      <p className="flex items-start gap-[var(--space-2)] text-[var(--text-sm)] text-[var(--danger)]">
        <CircleX size={16} strokeWidth={1.5} className="mt-[2px] shrink-0" aria-hidden="true" />
        <span>{businessReason(errorCode)}</span>
      </p>
    );
  }

  return (
    <p className="text-[var(--text-sm)] text-[var(--muted)]">
      {STATUS_TEXT[status ?? 'pending'] ?? '状态未知'}
    </p>
  );
}

/**
 * [需资深] 错误码 → 业务语言。
 * **禁止把后端错误码直接抛给老板**（那是系统语汇），
 * 也禁止暴露检测阈值（SPEC noSystemBehaviorLeak）。
 * 未覆盖的码统一说「需要你补一个授权才能继续」，而不是把码显示出来 ——
 * 显示码会让老板以为他在用开发工具。
 */
function businessReason(errorCode?: string | null): string {
  switch (errorCode) {
    case 'TARGET_REQUIRES_JS_RENDER':
      return '这个网址需要浏览器才能加载，本阶段还做不到。';
    case 'skipped_robots_disallowed':
      return '这个网站不允许抓取，跳过了。';
    case 'InvalidCredential':
      return '模型密钥不可用，需要检查后重新填写。';
    case 'CapabilityInsufficient':
      return '当前模型不支持这个能力，需要换一个模型。';
    default:
      return '需要你补上授权才能继续。';
  }
}

/** ISO 时间 → 「14:32」。缺时间时退回步骤序号，保证每行都有可读标识。 */
function formatStepTime(iso?: string | null, ordinal?: number): string {
  if (!iso) return ordinal ? `第 ${ordinal} 步` : '';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return ordinal ? `第 ${ordinal} 步` : '';
  return `${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`;
}