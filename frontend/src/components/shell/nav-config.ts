/**
 * 导航配置。
 *
 * 约束：顶级导航**最多 6 项**（工作记忆原则，SPEC §7.3 允许 6 项为例外）。
 * Phase 2 只实现 3 个页面 —— 导航只暴露**已可用**路由，
 * 未实现的页面不占位：放一个点了跳 404 的入口，比不放更伤信任
 * （老板无法区分「功能没做」和「坏了」）。
 *
 * Phase 3 追加 /pending /tasks /knowledge /settings 时在此加一行即可。
 * 图标名取自 design-tokens icon.verifiedNames.features，已核 lucide-react@1.57.0 真实导出。
 */

import { Briefcase, LayoutGrid } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: '运营',
    items: [{ href: '/', label: '每日汇报', icon: LayoutGrid }],
  },
  {
    title: '资产',
    items: [{ href: '/jobs', label: '岗位库', icon: Briefcase }],
  },
];