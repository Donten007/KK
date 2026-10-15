"""迁移 0007：pending_items 补 stopped_step 列。

前端 /pending 页需要展示「停在哪一步」（业务语言步骤标题）。
该值在软暂停那一刻写入，事后无法从 goal 反推（步骤标题随输入变化），
因此必须是列而不是运行时计算。goal_title 与 waiting_days 由查询时 join/computed
提供，不落列（避免双写漂移）。
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pending_items", sa.Column("stopped_step", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_items", "stopped_step")