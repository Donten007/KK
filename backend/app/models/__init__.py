"""模型注册表：env.py 与测试导入本包以保证全部模型进入 Base.metadata。

新增模型必须在此登记，否则 Alembic autogen 看不到它（静默漏迁移）。
"""

from app.models.audit import AuditLog
from app.models.goal import (
    Goal,
    GoalEvent,
    GoalProgressState,
    TaskArtifact,
    TaskStep,
)
from app.models.job import Agent, JobTemplate
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_link import UserTenantLink
from app.models.user import RefreshToken, User

__all__ = [
    "Agent",
    "AuditLog",
    "Goal",
    "GoalEvent",
    "GoalProgressState",
    "JobTemplate",
    "RefreshToken",
    "TaskArtifact",
    "TaskStep",
    "Tenant",
    "TenantMember",
    "User",
    "UserTenantLink",
]
