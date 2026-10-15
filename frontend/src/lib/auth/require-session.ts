import { redirect } from 'next/navigation';
import { getSession } from '@/lib/api/session-store';

/**
 * 路由守卫（Server Component 版）。
 *
 * [需资深] 只做"有无会话"的粗判，不在 Edge 层解 JWT ——
 * 解 JWT 需要密钥，middleware 跑在 Edge runtime，密钥注入路径不同，
 * 且在边缘解一遍 access token 会引入额外的密钥面。
 * 真正的鉴权由后端 RLS + 每个接口的 Bearer 校验兜底（SPEC §4.4）。
 * 这是纵深防御的第一层，不是唯一一层。
 *
 * 未登录 → /login，并带上 next 参数，登录后回原页面。
 */
export function requireSession(returnTo?: string): void {
  const session = getSession();
  if (session) return;
  const target = returnTo ? `/login?next=${encodeURIComponent(returnTo)}` : '/login';
  redirect(target);
}