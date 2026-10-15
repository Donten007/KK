import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AuthForm } from '@/components/auth/auth-form';
import { MarketingShell } from '@/components/auth/marketing-shell';
import { getSession } from '@/lib/api/session-store';

export const metadata: Metadata = {
  title: '注册',
  description: '雇下第一个 AI 员工。写好岗位说明书，它今天就上岗。',
};

/** 已登录用户访问注册页 → 直接回工作台，同 /login 口径 */
export default function RegisterPage() {
  if (getSession()) redirect('/');

  // 同壳三差异（UIUX-marketing §2.2）：标题 / 副标题 / 导航链接方向
  return (
    <MarketingShell
      headline="雇下第一个 AI 员工。"
      lead="写好岗位说明书，它今天就上岗。按结果看产出，不按过程烧时间。"
      navLink={{ href: '/login', label: '已有团队？登录' }}
    >
      <AuthForm mode="register" />
    </MarketingShell>
  );
}
