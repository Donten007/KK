/**
 * 内联防闪白脚本。
 *
 * [需资深] 必须在 HTML 解析阶段同步执行 —— 放到 useEffect 里会晚一帧，
 * 深色用户会看到白底闪一下再变深色。原理与 use-theme.ts 的
 * resolveInitialTheme 保持一致：显式选择 > 系统偏好 > 默认深色。
 */
const SCRIPT = `(function(){try{
var t=localStorage.getItem('evowork.theme');
if(t!=='dark'&&t!=='light'){
t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
}
document.documentElement.setAttribute('data-theme',t);
}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: SCRIPT }} suppressHydrationWarning />;
}