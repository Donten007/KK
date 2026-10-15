/**
 * 认证相关端点。
 *
 * 纪律：请求体与响应体类型一律从 openapi 生成的 paths / components 取，
 * **禁止手写**（手写会与后端静默漂移，且绕过 openapi 类型这道防线）。
 * inline requestBody 由 openapi-typescript 生成在 paths 下，用路径索引提取。
 */

import { ApiError, apiRequest } from './client';
import { clearSession, getSession, setSession } from './session-store';
import type { components, paths } from '@/types/api';

export type AuthResult = components['schemas']['AuthResult'];
export type CurrentUser = components['schemas']['User'];

type RegisterBody = paths['/api/v1/auth/register']['post']['requestBody']['content']['application/json'];
type LoginBody = paths['/api/v1/auth/login']['post']['requestBody']['content']['application/json'];

/**
 * 令牌落地。
 * 契约违约（响应缺字段）统一转成 ApiError，让表单层能显示可读文案，
 * 而不是抛一个裸 Error 变成白屏。
 */
function persistTokens(result: AuthResult): AuthResult {
  if (!result.tokens) {
    throw new ApiError(5001, '登录响应不完整，请稍后重试。');
  }
  try {
    setSession(result.tokens);
  } catch {
    throw new ApiError(5001, '登录响应不完整，请稍后重试。');
  }
  return result;
}

export async function register(input: RegisterBody): Promise<AuthResult> {
  const result = await apiRequest<AuthResult>('/api/v1/auth/register', {
    method: 'POST',
    body: input,
    anonymous: true,
  });
  return persistTokens(result);
}

export async function login(input: LoginBody): Promise<AuthResult> {
  const result = await apiRequest<AuthResult>('/api/v1/auth/login', {
    method: 'POST',
    body: input,
    anonymous: true,
  });
  return persistTokens(result);
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<null>('/api/v1/auth/logout', { method: 'POST' });
  } finally {
    // 无论后端是否成功，本地必须清干净 —— 用户点了登出就不该还留在页面上
    clearSession();
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  if (!getSession()) return null;
  try {
    return await apiRequest<CurrentUser>('/api/v1/auth/me');
  } catch {
    return null;
  }
}