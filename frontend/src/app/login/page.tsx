import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AuthForm } from '@/components/auth/auth-form';
import { WorkbenchPreview } from '@/components/auth/workbench-preview';
import { getSession } from '@/lib/api/session-store';

export const metadata: Metadata = {
  title: '登录',
  description: '登录 EvoWork，查看你的 AI 员工今天做了什么。',
};

/** 已登录用户访问登录页 → 直接回工作台，不让老板做无意义的二次决策 */
export default function LoginPage() {
  if (getSession()) redirect('/');

  return (
    <main className="flex min-h-dvh items-center justify-center bg-[var(--bg)] px-[var(--space-6)] py-[var(--space-8)]">
      <div className="flex w-full max-w-[960px] flex-col items-center justify-between gap-[var(--space-12)] lg:flex-row lg:gap-[var(--space-16)]">
        <WorkbenchPreview />
        <AuthForm />
      </div>
    </main>
  );
}