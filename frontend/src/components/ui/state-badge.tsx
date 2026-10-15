'use client';

/**
 * 状态标记（三通道）。
 *
 * P0 无障碍硬约束：状态**必须**同时由颜色 + 图标 + 文字承载。
 * 依据：design-tokens color.cvdFindings —— 红绿色盲下 warn 与 danger
 * 模拟对比度为 1.00:1（完全同色），全色盲下五种语义色全部塌成灰。
 * 只靠颜色表达状态 = 对一部分用户完全不可读。
 *
 * 图标与文案**照抄** UIUX §11.1 的状态表，不允许自选近义图标。
 */

import {
  BadgeQuestionMark,
  CircleCheck,
  CircleDashed,
  CircleDollarSign,
  CircleX,
  Hand,
  LoaderCircle,
  LockKeyhole,
  Pause,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';

/** 10 态，与 design-tokens state.map 一一对应 */
export type StateKey =
  | 'running'
  | 'stopping'
  | 'idle'
  | 'needs-human'
  | 'done'
  | 'failed'
  | 'attention'
  | 'budget'
  | 'skipped'
  | 'auth-needed';

interface StateDef {
  icon: LucideIcon;
  /** 状态文字。budget 态需替换 NN% 为实际百分比 */
  label: string;
  color: string;
  spins?: boolean;
}

export const STATE_MAP: Record<StateKey, StateDef> = {
  running: { icon: LoaderCircle, label: '运行中', color: 'var(--accent)', spins: true },
  stopping: { icon: CircleDashed, label: '正在中止…', color: 'var(--warn)', spins: true },
  idle: { icon: Pause, label: '待命', color: 'var(--muted)' },
  // needs-human 用 Hand（举手）不是 TriangleAlert：
  // 「员工停下来问你」是协作不是故障，用红色会让正向设计变成信任负债（UIUX §8.2）
  'needs-human': { icon: Hand, label: '等你确认', color: 'var(--info)' },
  done: { icon: CircleCheck, label: '已完成', color: 'var(--success)' },
  failed: { icon: CircleX, label: '失败', color: 'var(--danger)' },
  attention: { icon: TriangleAlert, label: '需关注', color: 'var(--warn)' },
  budget: { icon: CircleDollarSign, label: 'API 预算', color: 'var(--warn)' },
  skipped: { icon: BadgeQuestionMark, label: '已跳过', color: 'var(--muted)' },
  'auth-needed': { icon: LockKeyhole, label: '需授权', color: 'var(--muted)' },
};

interface StateBadgeProps {
  state: StateKey;
  /** 覆盖默认文案，例如 budget 态传 "API 预算 82%" */
  label?: string;
  size?: number;
}

export function StateBadge({ state, label, size = 16 }: StateBadgeProps) {
  const def = STATE_MAP[state];
  const Icon = def.icon;

  return (
    <span
      className="inline-flex items-center gap-1.5 text-[var(--text-sm)]"
      style={{ color: def.color }}
    >
      <Icon
        size={size}
        strokeWidth={1.5}
        className={def.spins ? 'icon-spin' : undefined}
        aria-hidden="true"
      />
      <span>{label ?? def.label}</span>
    </span>
  );
}