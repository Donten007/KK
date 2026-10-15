import type { Metadata } from 'next';
import { requireSession } from '@/lib/auth/require-session';
import { JobLibraryView } from '@/components/jobs/job-library-view';

export const metadata: Metadata = {
  title: '岗位库',
  description: '挑一个岗位，AI 员工会按这个岗位的职责自己接工作。',
};

export default function JobsPage() {
  requireSession('/jobs');
  return <JobLibraryView />;
}