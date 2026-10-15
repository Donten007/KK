/**
 * 登录墙内布局（Shell 装配层）。
 *
 * 职责边界：本文件只做「侧边栏 + 顶栏 + 内容区」的装配，
 * **不包含任何业务逻辑**。业务在 (workspace)/ 下的各页面里。
 */

import type { ReactNode } from 'react';
import { Sidebar } from '@/components/shell/sidebar';
import { MobileTabBar } from '@/components/shell/mobile-tab-bar';
import { WorkspaceShellClient } from '@/components/shell/workspace-shell-client';

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh overflow-hidden bg-[var(--bg)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <WorkspaceShellClient />
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <MobileTabBar />
    </div>
  );
}