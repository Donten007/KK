"""迁移 0006：播种岗位模板（SPEC §6.2 job_templates 平台级）。

新增岗位模板是平台级数据（无 RLS），由迁移播种保证「模板」与「代码」
同步发布——代码引用 steps_def 的工具名，模板里若没有对应 tool_name，
F6-lite 图执行时会 unknown_tool 失败。两者必须同版本上线。
"""

from __future__ import annotations

import json
import uuid
from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _template_row(tpl: dict) -> dict:
    return {
        "id": uuid.uuid4(),
        "code": tpl["code"],
        "name": tpl["name"],
        "icon": tpl["icon"],
        "summary": tpl["summary"],
        "deliverables": json.dumps(tpl["deliverables"], ensure_ascii=False),
        "prerequisites": json.dumps(tpl["prerequisites"], ensure_ascii=False),
        "required_caps": json.dumps(tpl["required_caps"], ensure_ascii=False),
        "optional_caps": json.dumps(tpl["optional_caps"], ensure_ascii=False),
        "expected_idle_steps": tpl["expected_idle_steps"],
        "expected_total_steps": tpl["expected_total_steps"],
        "baseline_minutes_per_run": tpl["baseline_minutes_per_run"],
        "difficulty": tpl["difficulty"],
        "sort_order": tpl["sort_order"],
        "steps_def": json.dumps(tpl["steps_def"], ensure_ascii=False),
    }


def upgrade() -> None:
    from app.jobs.weekly_report import WEEKLY_REPORT_TEMPLATE

    row = _template_row(WEEKLY_REPORT_TEMPLATE)
    # 幂等：模板已存在则跳过（重复执行迁移不报错）
    # 【需资深】op.execute 的第二位置参数是 execution_options 不是 bind params，
    # 参数必须用 .bindparams() 链在 text 上（CI 首跑曾因传法错误 TypeError）
    op.execute(
        sa.text(
            """
            INSERT INTO job_templates (
                id, code, name, icon, summary, deliverables, prerequisites,
                required_caps, optional_caps, expected_idle_steps,
                expected_total_steps, baseline_minutes_per_run, difficulty,
                sort_order, steps_def
            ) VALUES (
                :id, :code, :name, :icon, :summary,
                CAST(:deliverables AS jsonb), CAST(:prerequisites AS jsonb),
                CAST(:required_caps AS jsonb), CAST(:optional_caps AS jsonb),
                :expected_idle_steps, :expected_total_steps,
                :baseline_minutes_per_run, :difficulty, :sort_order,
                CAST(:steps_def AS jsonb)
            )
            ON CONFLICT (code) DO NOTHING
            """
        ).bindparams(**row)
    )


def downgrade() -> None:
    from app.jobs.weekly_report import WEEKLY_REPORT_TEMPLATE

    op.execute(
        sa.text("DELETE FROM job_templates WHERE code = :code").bindparams(
            code=WEEKLY_REPORT_TEMPLATE["code"]
        ),
    )