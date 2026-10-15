import type { components } from '@/types/api';

type JobTemplate = components['schemas']['JobTemplate'];

/**
 * 岗位目录（平台级静态内容，前端持有）。
 *
 * 为什么前端持有一份目录而不是只等后端：
 * 岗位模板是**平台级共享内容**（SPEC §6.2：无 RLS、平台维护），不是租户数据。
 * 后端 `/api/v1/job-templates` 端点尚未落地，前端以本目录兜底渲染已上线岗位，
 * 后端端点就绪后（返回非空列表）自动优先采用后端数据 —— 目录只是并行开发期的兜底，
 * 不是第二真相来源。
 *
 * ## 卡片数 = 已上线岗位数（禁「先雇一个」式暗示）
 * 只有已上线的岗位出现在这里：#1 竞品监控日报 / #2 周报汇总 / #4 客户跟进催办。
 * #3 发票信息核对（需 vision）、#5 电商订单录入（需 F6-full）未上线，**不占位**。
 *
 * 文案依据：SPEC §2.4（岗位清单）+ JOB-TEMPLATE-COPY.md（卡片五要素）+ UIUX §8.3。
 * 四组技术字段是岗位「上架」的前置（SPEC §2.4），卡片不渲染、仅保证类型完整；
 * 步骤数取值对齐 SPEC §2.4 的步骤数区间，后端种子落地后以 DB 为准。
 */
export const JOB_CATALOG: JobTemplate[] = [
  {
    id: 'competitor_monitor_daily',
    name: '竞品监控日报',
    icon: 'Radar',
    summary: '每天早上 8 点，看完 5 家竞品的价格与动作，把变化写成一份日报',
    deliverables: ['竞品日报-{日期}.xlsx', '异常波动清单'],
    prerequisites: [],
    required_caps: ['tool_use'],
    optional_caps: ['long_context'],
    expected_idle_steps: 3,
    expected_total_steps: 8,
    difficulty: 'low',
  },
  {
    id: 'weekly_report_summary',
    name: '周报汇总',
    icon: 'FileSpreadsheet',
    summary: '每周五下午，把团队交上来的周报表汇总成一份总周报，落后和超额的都标出来',
    deliverables: ['团队周报汇总-{周次}.xlsx', '进度风险清单'],
    prerequisites: ['团队周报表'],
    required_caps: ['tool_use'],
    optional_caps: [],
    expected_idle_steps: 3,
    expected_total_steps: 6,
    difficulty: 'low',
  },
  {
    id: 'customer_followup_reminder',
    name: '客户跟进催办',
    icon: 'MessageSquare',
    summary: '每天扫一遍客户跟进表，把该跟进没跟进的客户挑出来，写好催办话术等你确认',
    deliverables: ['跟进提醒清单', '催办话术'],
    prerequisites: ['客户跟进表'],
    required_caps: ['tool_use'],
    optional_caps: [],
    expected_idle_steps: 4,
    expected_total_steps: 10,
    difficulty: 'medium',
  },
];
