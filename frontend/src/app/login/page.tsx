import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AuthForm } from '@/components/auth/auth-form';
import { MarketingShell } from '@/components/auth/marketing-shell';
import { getSession } from '@/lib/api/session-store';

export const metadata: Metadata = {
  title: '登录',
  description: '登录 EvoWork，查看你的 AI 员工今天交了什么汇报。',
};

/** 已登录用户访问登录页 → 直接回工作台，不让老板做无意义的二次决策 */
export default function LoginPage() {
  if (getSession()) redirect('/');

  // 文案按 UIUX-marketing §5 文案表：面向回访用户的价值确认，实词禁空洞
  return (
    <MarketingShell
      headline="你的 AI 员工，刚交了新汇报。"
      lead="登录后查看每个员工的产出、汇报与成本。"
      navLink={{ href: '/register', label: '没有团队？注册' }}
    >
      <AuthForm mode="login" />
    </MarketingShell>
  );
}
