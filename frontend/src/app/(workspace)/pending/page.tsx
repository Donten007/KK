import type { Metadata } from 'next';
import { requireSession } from '@/lib/auth/require-session';
import { PendingQueue } from '@/components/pending/pending-queue';

export const metadata: Metadata = {
  title: '待确认',
  description: '员工拿不准的事停在这里，带着依据等你拍板。',
};

/** 路由守卫：未登录去/login */
export default function PendingPage() {
  requireSession('/pending');
  return <PendingQueue />;
}
