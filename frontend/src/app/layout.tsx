import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import { ThemeScript } from '@/components/shell/theme-script';
import '../styles/globals.css';

/**
 * 字体：Inter（正文）+ JetBrains Mono（计量数字）。
 * 二者均为 OFL-1.1，允许商用。design-tokens typography.family 已锁定。
 */
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

/**
 * 根布局。
 * 入口文件职责：只装配 html/body/字体/主题脚本，不写业务逻辑。
 */
export const metadata: Metadata = {
  title: {
    default: 'EvoWork — 你的 AI 员工在工作',
    template: '%s | EvoWork',
  },
  description:
    '让 AI 员工替你盯竞品、写日报、发客户邮件。每天一份汇报，花的钱看得懂。',
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="dark" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className={`${inter.variable} ${jetbrainsMono.variable}`}>{children}</body>
    </html>
  );
}