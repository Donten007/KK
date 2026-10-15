'use client';

/**
 * 待命员工名单。
 *
 * ## 验收标准 10 的两段式渲染（PM F4 硬要求）
 * 顶部**必须先声明总数**（在岗 X / 待命 Y），让老板一眼知道分母。
 * 待命员工**必须列出姓名 + 原因**，禁止「+2 名待命」式折叠计数。
 *
 * 理由与折叠禁令同源：**折叠即等于隐藏**。老板无法区分「没活干」和
 * 「被跳过了」，因此省略比报错更伤信任。
 *
 * 若某员工本应执行但未执行（异常），用 CircleAlert 显式标出，
 * 同样不折叠。
 */

import { CircleAlert, Pause } from 'lucide-react';
import type { components } from '@/types/api';

type AgentReport = components['schemas']['AgentReport'];

/** 未执行的原因映射。优先用后端给出的业务语言原因，兜底按 status 归类。 */
const NOT_RUN_REASON: Record<Exclude<AgentReport['status'], undefined>, string> = {
  completed: '今天正常在岗',
  partial: '今天只完成了一部分',
  stuck: '今天卡住了',
  not_run: '今天没有运行',
};

/** 只有这两个状态代表「待命」，需要列出原因 */
const STANDBY_STATUSES = new Set<NonNullable<AgentReport['status']>>(['not_run']);

export function DutySummary({
  onDutyCount,
  standbyCount,
  agents,
}: {
  onDutyCount: number;
  standbyCount: number;
  agents: AgentReport[];
}) {
  const standby = agents.filter(
    (a) => a.status && STANDBY_STATUSES.has(a.status) && a.status !== 'completed',
  );

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      {/* 第一段：先声明总数 */}
      <p className="text-[var(--text-base)] text-[var(--fg-1)]">
        今天 {onDutyCount} 名员工在岗，{standbyCount} 名待命
      </p>

      {/* 第二段：待命员工必须列姓名 + 原因，禁止折叠计数 */}
      {standby.length > 0 ? (
        <ul className="flex flex-col gap-[var(--space-1)]">
          {standby.map((agent, index) => {
            const isAbnormal = agent.status === 'stuck';
            const reason =
              (agent.stopped_section as { reason?: string } | undefined)?.reason ??
              NOT_RUN_REASON[agent.status ?? 'not_run'];

            return (
              <li
                key={agent.agent_id ?? `standby-${index}`}
                className="flex items-center gap-[var(--space-2)] text-[var(--text-sm)] text-[var(--fg-2)]"
              >
                {isAbnormal ? (
                  <CircleAlert size={16} strokeWidth={1.5} className="shrink-0 text-[var(--warn)]" aria-hidden="true" />
                ) : (
                  <Pause size={16} strokeWidth={1.5} className="shrink-0 text-[var(--muted)]" aria-hidden="true" />
                )}
                <span className="text-[var(--fg-1)]">{agent.agent_name ?? '未命名员工'}</span>
                <span>{reason}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}