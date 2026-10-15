import type { Metadata } from 'next';
import { requireSession } from '@/lib/auth/require-session';
import { DailyReportView } from '@/components/report/daily-report-view';

export const metadata: Metadata = {
  title: '每日汇报',
  description: '今天做完了什么、要你管什么、花了多少钱，一页看完。',
};

/** 路由守卫：未登录去/login */
export default function HomePage() {
  requireSession('/');
  return <DailyReportView />;
}