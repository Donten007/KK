'use client';

/**
 * 数据获取 hook。
 *
 * [需资深] 为什么不用 SWR / React Query：
 * Phase 2 只有 5 个端点，引入数据层要额外锁版本（SPEC §4.1 锁版本纪律），
 * 且它们的重试/缓存策略并不适合本产品 —— 尤其是**不能自动重试**：
 * 日报里 `total_this_month` 是信任指标，自动重试掩盖失败会造成
 * 「数字看起来一直有但其实没加载成功」的沉默错误。
 *
 * 失败必须显式暴露给用户，这是省略比报错更伤信任原则的直接推论。
 *
 * [实习生可做] 增加新数据源时复制本 hook 的模式：区分 loading / error / data
 * 三态，error 必须回传原始错误对象让上层决定怎么讲。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiRequest } from '@/lib/api/client';

export type AsyncState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: null; error: ApiError };

export function useApiResource<T>(path: string | null, deps: unknown[] = []): {
  state: AsyncState<T>;
  reload: () => void;
} {
  const [inner, setState] = useState<{ path: string | null; value: AsyncState<T> }>(() => ({
    path,
    // path 为 null = 不请求。惰性初始化直接给终态，避免 effect 里同步 setState
    value: path === null ? { status: 'success', data: null as T, error: null } : INITIAL_LOADING,
  }));

  // 请求路径变化时，同步重置为 loading —— 派生值，不需要 effect
  const state = inner.path === path ? inner.value : INITIAL_LOADING;
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  // 防止组件卸载后 setState：快速切页时慢请求回来会打到已卸载的树
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (path === null) return;

    let cancelled = false;

    void (async () => {
      try {
        const data = await apiRequest<T>(path);
        if (!cancelled && aliveRef.current) {
          setState({ path, value: { status: 'success', data, error: null } });
        }
      } catch (error) {
        if (cancelled || !aliveRef.current) return;
        const apiError = error instanceof ApiError ? error : new ApiError(0, '出了点问题，请稍后重试。');
        setState({ path, value: { status: 'error', data: null, error: apiError } });
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);

  return { state, reload };
}

const INITIAL_LOADING: AsyncState<never> = { status: 'loading', data: null, error: null };