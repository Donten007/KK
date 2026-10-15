import type { Metadata } from 'next';
import { requireSession } from '@/lib/auth/require-session';
import { TrialResultView } from '@/components/trial/trial-result-view';

export const metadata: Metadata = {
  title: '试跑结果',
  description: '看这个员工靠不靠谱：干了什么、哪里要你确认、花了多少钱。',
};

/**
 * Next.js 16 的 params 是异步的，必须 await。
 * [实习生可做] 见到 params/searchParams 一律 await，不要按旧版同步用法写。
 */
export default async function TrialPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  requireSession(`/jobs/${id}/trial`);

  return <TrialResultView goalId={id} />;
}