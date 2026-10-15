"""岗位定义包（Phase 3：周报汇总等新增岗位的模板 + executor）。"""

from app.jobs.weekly_report import WEEKLY_REPORT_TEMPLATE, WeeklyReportExecutor

__all__ = ["WEEKLY_REPORT_TEMPLATE", "WeeklyReportExecutor"]
