/**
 * 主题切换。
 *
 * SPEC §7.2 锁定优先级：**用户显式选择 > 系统偏好**，深色为默认。
 * 首屏跟随系统（SPEC §7.2 + design-tokens meta.defaultTheme = dark）。
 *
 * [需资深] 防闪白：主题必须在 HTML 解析阶段就落到 <html data-theme> 上，
 * 否则深色用户会看到一帧浅色背景再跳变。这里靠 layout.tsx 里的内联
 * blocking script 完成，hook 只负责切换与持久化，两处共用同一份解析逻辑。
 */

import { useCallback, useState } from 'react';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'evowork.theme';

/** 首屏内联脚本与本函数共用同一套判定，保证两处结论一致。 */
function resolveInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'dark' || stored === 'light') return stored;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme);
}

/**
 * SSR 侧的初值。服务端没有 window，永远按默认深色渲染；
 * 真实主题由 layout.tsx 的内联脚本在 hydration 前落到 <html> 上，
 * 客户端首次渲染时再从 DOM 读回，避免 hydration 不匹配。
 */
function readDomTheme(): Theme {
  if (typeof document === 'undefined') return 'dark';
  const attr = document.documentElement.getAttribute('data-theme');
  return attr === 'light' ? 'light' : 'dark';
}

export function useTheme() {
  // 惰性初始化：不走 useEffect + setState，避免级联渲染
  const [theme, setThemeState] = useState<Theme>(readDomTheme);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      window.localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }, []);

  return { theme, setTheme, toggleTheme };
}

export { STORAGE_KEY as THEME_STORAGE_KEY, resolveInitialTheme };