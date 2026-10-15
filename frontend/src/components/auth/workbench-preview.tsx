'use client';

/**
 * 工作台缩略预览（登录页左栏）。
 *
 * UIUX §7.2 反 Hero 模式：这不是抽象 3D 图形，是**产品真实形态** ——
 * 用户第一眼就知道自己买的是什么。若换成插画/渐变装饰，
 * 就退回成普通 SaaS 落地页，老板对"AI 员工"没有预期。
 *
 * 三通道纪律在此也成立：运行中/待命各带图标 + 文字，不靠颜色单独表达状态。
 */

import { LoaderCircle, Pause } from 'lucide-react';

interface PreviewAgent {
  name: string;
  status: 'running' | 'idle';
  /** 运行中时的业务语言描述 */
  current?: string;
  /** 运行时长与完成度 */
  elapsed?: string;
  progress?: string;
}

const PREVIEW_AGENTS: PreviewAgent[] = [
  {
    name: '市场专员',
    status: 'running',
    current: '正在检索：2026Q3 华东区渠道台账',
    elapsed: '本班次 2 小时 14 分',
    progress: '完成 7/9',
  },
  {
    name: '内容专员',
    status: 'running',
    current: '正在生成：产品周报草稿',
  },
  { name: '客服专员', status: 'idle' },
];

export function WorkbenchPreview() {
  return (
    <div className="hidden w-full max-w-[520px] flex-col gap-[var(--space-3)] lg:flex">
      <p className="text-[var(--text-sm)] text-[var(--fg-2)]">
        这是你的员工上班时看到的样子。
      </p>

      <ul className="flex flex-col gap-[var(--space-3)]">
        {PREVIEW_AGENTS.map((agent) => (
          <li
            key={agent.name}
            className="rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--surface-2)] p-[var(--card-padding)]"
          >
            <div className="flex items-center gap-[var(--space-2)]">
              {agent.status === 'running' ? (
                <LoaderCircle
                  size={16}
                  strokeWidth={1.5}
                  className="icon-spin text-[var(--accent)]"
                  aria-hidden="true"
                />
              ) : (
                <Pause size={16} strokeWidth={1.5} className="text-[var(--muted)]" aria-hidden="true" />
              )}
              <span className="text-[var(--text-md)] font-[var(--weight-medium)] text-[var(--fg-1)]">
                {agent.name}
              </span>
              {/* 图标 + 文字双通道 */}
              <span className="text-[var(--text-xs)] text-[var(--muted)]">
                {agent.status === 'running' ? '运行中' : '待命'}
              </span>
            </div>

            {agent.current ? (
              <p className="mt-[var(--space-2)] text-[var(--text-sm)] text-[var(--fg-2)]">
                {agent.current}
              </p>
            ) : null}

            {agent.elapsed ? (
              <p className="tabular mt-[var(--space-2)] text-[var(--text-xs)] text-[var(--muted)]">
                {agent.elapsed} · {agent.progress}
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      {/* 底部一行承诺：这是本产品的核心销售点，纯 BYOK，不放在注册表单里 */}
      <p className="text-[var(--text-xs)] text-[var(--muted)]">
        它停下来问你的每个问题，都会带上它查到的东西。
      </p>
    </div>
  );
}