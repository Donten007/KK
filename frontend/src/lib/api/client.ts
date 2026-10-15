/**
 * API 客户端。
 *
 * 契约来源：docs/openapi.yaml。请求/响应类型一律从 src/types/api.d.ts 取，
 * **禁止手写请求体或响应体类型**——手写即与后端漂移，且绕过了 openapi 的第一道防线。
 *
 * 统一 Envelope 处理：code === 0 为成功，其余见 SPEC §5.4 错误码规范。
 */

import { clearSession, getSession, needsRefresh, refreshTokens } from './session-store';

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

/**
 * SPEC §5.4 业务错误码 → 面向老板的可读文案。
 *
 * 纪律：技术码不直接抛给用户；新增码必须先在 SPEC §5.4 落表再在此登记，
 * 禁止在客户端凭空造码。2001「余额不足」的文案口径受纯 BYOK 约束，
 * 对外只说 API 预算，绝不说「充值/余额」（design-tokens copy.byokConstraint）。
 */
const ERROR_MESSAGES: Record<number, string> = {
  1001: '填写的内容有问题，请检查后重试。',
  1002: '登录已失效，请重新登录。',
  1003: '你的账号没有这个操作权限。',
  1004: '没有找到对应的内容。',
  1005: '内容已存在，请换一个。',
  1006: '文件超出了允许的大小。',
  1007: '操作太频繁了，请稍后再试。',
  2001: '这个员工的 API 预算不够用了，请调整预算上限。',
  2002: '本月 API 预算已经用完，请调整后重试。',
  3001: '当前模型不支持这个能力，请换一个模型。',
  3002: '模型服务暂时不可用，请稍后重试。',
  3003: '这个 API Key 不可用，请检查后重新填写。',
  4001: '这个网址需要浏览器才能加载，本阶段暂不支持。',
  4002: '这个网站不允许抓取，已跳过。',
  5001: '服务出了点问题，请稍后重试。',
};

export class ApiError extends Error {
  readonly code: number;
  readonly isAuthError: boolean;
  readonly isNetworkError: boolean;

  constructor(code: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.isAuthError = code === 1002;
    this.isNetworkError = code === 0;
  }
}

interface Envelope<T> {
  code: number;
  data: T | null;
  message: string;
}

/** [需资深] 单次网络请求超时上限。SSE 与流式接口不走本客户端，单独处理。 */
const REQUEST_TIMEOUT_MS = 15_000;

async function withTimeout(input: string, init: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = 0;
  let message = '';
  try {
    const body = (await res.json()) as Envelope<unknown>;
    code = body.code ?? 0;
    message = body.message ?? '';
  } catch {
    // 非 JSON 响应（网关错误页等），保留空码
  }
  const friendly = ERROR_MESSAGES[code] ?? (res.ok ? '' : '服务暂时没有响应，请稍后重试。');
  return new ApiError(code, friendly || message);
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** 无需登录态的端点（登录/注册/刷新） */
  anonymous?: boolean;
}

/**
 * 带登录态的请求。会话过期时自动刷新一次并重放；刷新失败则清会话。
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, anonymous = false } = options;

  const send = async (accessToken: string | null): Promise<Response> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

    return withTimeout(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
  };

  let token: string | null = null;
  if (!anonymous) {
    const session = getSession();
    if (session && needsRefresh(session)) {
      token = await refreshTokens(API_BASE);
    } else {
      token = session?.accessToken ?? null;
    }
    if (token === null && session === null) {
      throw new ApiError(1002, ERROR_MESSAGES[1002] as string);
    }
  }

  let res: Response;
  try {
    res = await send(token);
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw new ApiError(0, '请求超时，请检查网络后重试。');
    }
    throw new ApiError(0, '连不上服务器，请确认后端已启动。');
  }

  // 401 且非匿名端点 → 尝试刷新后重放一次
  if (res.status === 401 && !anonymous) {
    const refreshed = await refreshTokens(API_BASE);
    if (refreshed) {
      res = await send(refreshed);
    } else {
      clearSession();
      throw new ApiError(1002, ERROR_MESSAGES[1002] as string);
    }
  }

  if (!res.ok) throw await toApiError(res);

  const payload = (await res.json()) as Envelope<T>;
  if (payload.code !== 0) {
    throw new ApiError(payload.code, ERROR_MESSAGES[payload.code] ?? payload.message ?? '操作没有成功。');
  }
  return payload.data as T;
}