/**
 * 会话令牌存储。
 *
 * [需资深] 安全权衡：access token (15min) 存内存，refresh token (7d) 存 localStorage。
 * 理由：access token 放内存可降低 XSS 长期窃取风险；refresh token 必须跨会话存活
 * 否则用户每次刷新都要重新登录，这对「不是技术用户」的老板是不可接受的体验。
 * 若后端后续支持 httpOnly cookie 下发 refresh token，应立即改为 cookie 方案——
 * 这里的取舍是为了 Phase 2 骨架可运行，不是终态安全方案。
 *
 * 单例在模块作用域，SSR 与客户端各自一份，符合 App Router 隔离模型。
 */

export interface Session {
  accessToken: string;
  refreshToken: string;
  /** access token 过期时刻（epoch ms），用于提前刷新 */
  expiresAt: number;
}

const REFRESH_KEY = 'evowork.session.refresh';
const EXPIRES_KEY = 'evowork.session.expiresAt';

/** 提前 60s 刷新，避免边界时刻的 401 */
const REFRESH_SKEW_MS = 60_000;

let memory: Session | null = null;
let refreshing: Promise<string | null> | null = null;

function isBrowser(): boolean {
  return typeof window !== 'undefined';
}

export function getSession(): Session | null {
  if (memory) return memory;
  if (!isBrowser()) return null;

  const refreshToken = window.localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return null;

  // access token 只在内存，SSR/刷新后必然缺失 → 视为需要用 refresh 换新
  memory = {
    accessToken: '',
    refreshToken,
    expiresAt: Number(window.localStorage.getItem(EXPIRES_KEY) ?? '0'),
  };
  return memory;
}

/**
 * 写入会话。
 *
 * [需资深] 这里做**显式字段校验**而非直接断言类型。
 * openapi 生成的 TokenPair 所有字段都是 optional（契约里没有 required 列表），
 * 若直接断言，一个缺字段的响应会把 `undefined` 写进 token 存储 ——
 * 编译通过、运行不报错，但每个请求都带 `Bearer undefined`，症状是
 * 「随机 401」，排查成本极高。缺字段就是契约违约，必须当场失败。
 */
export function setSession(tokens: {
  access_token?: string | undefined;
  refresh_token?: string | undefined;
  expires_in?: number | undefined;
}): Session {
  const { access_token: accessToken, refresh_token: refreshToken, expires_in: expiresIn } = tokens;

  if (!accessToken || !refreshToken || typeof expiresIn !== 'number') {
    throw new Error('登录响应缺少必要的令牌字段，无法建立会话。');
  }

  const session: Session = {
    accessToken,
    refreshToken,
    // 后端未给 expires_in 时保守取15 分钟（SPEC §4.3Access Token 有效期）
    expiresAt: Date.now() + (expiresIn > 0 ? expiresIn : 900) * 1000,
  };
  memory = session;
  if (isBrowser()) {
    window.localStorage.setItem(REFRESH_KEY, session.refreshToken);
    window.localStorage.setItem(EXPIRES_KEY, String(session.expiresAt));
  }
  return session;
}

export function clearSession(): void {
  memory = null;
  if (isBrowser()) {
    window.localStorage.removeItem(REFRESH_KEY);
    window.localStorage.removeItem(EXPIRES_KEY);
  }
}

export function needsRefresh(session: Session | null): boolean {
  if (!session) return true;
  return Date.now() >= session.expiresAt - REFRESH_SKEW_MS;
}

/**
 * 刷新令牌。并发请求同时触发时共享同一个 Promise ——
 * refresh rotation 语义下旧 token 立即失效，若并发发出多个 refresh，
 * 第二次会被后端判定为重放并吊销该用户全部 refresh token。
 * 这是 SPEC §4.3 的硬约束，不是优化项。
 */
export function refreshTokens(baseUrl: string): Promise<string | null> {
  if (refreshing) return refreshing;

  const session = getSession();
  if (!session) return Promise.resolve(null);

  refreshing = (async () => {
    try {
      const res = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      });
      if (!res.ok) {
        clearSession();
        return null;
      }
      const body = (await res.json()) as { data?: { tokens?: { access_token: string; refresh_token: string; expires_in: number } } };
      const tokens = body.data?.tokens;
      if (!tokens) {
        clearSession();
        return null;
      }
      return setSession(tokens).accessToken;
    } catch {
      // 网络故障不等同于登录态失效，保留会话让用户重试，不清 token
      return null;
    } finally {
      refreshing = null;
    }
  })();

  return refreshing;
}

export { REFRESH_SKEW_MS };