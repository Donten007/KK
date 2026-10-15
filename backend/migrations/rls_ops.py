"""迁移 RLS 助手：让「建表」与「启用 RLS」在物理上无法分离（ADR-003 负面项对策）。

每张新租户表必须调用 create_tenant_isolation()：
- 缺 FORCE 等于没开（R1：表 owner 会静默绕过）
- 策略必须内联 NULLIF(current_setting(...))（R2：PL/pgSQL 会导致 170x 性能灾难）
- WITH CHECK 显式声明，保证 INSERT/UPDATE 也走同一策略
CI 有 pg_policies 断言兜底（tests/security/test_rls_policies.py）。
"""

from __future__ import annotations

# R2：唯一允许的策略表达式形态。出现任何其他形态（函数调用/PL/pgSQL）CI 即阻断。
_POLICY_EXPR = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)


def create_tenant_isolation(op, table: str) -> None:
    """对已建好的表启用 ENABLE + FORCE RLS 并创建内联隔离策略。

    顺序固定：ENABLE → FORCE → POLICY。FORCE 不可省（R1）。
    """
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING ({_POLICY_EXPR}) WITH CHECK ({_POLICY_EXPR})"
    )


def make_append_only(op, table: str, app_role: str = "opc_app") -> None:
    """审计类表：应用角色只插不改不删（SPEC §6.2 audit_logs）。

    角色不存在时跳过（dev/CI 环境可能未建角色），保证迁移可移植。
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{app_role}') THEN
                REVOKE UPDATE, DELETE ON "{table}" FROM {app_role};
            END IF;
        END $$;
        """
    )


def create_tenant_covering_index(op, table: str) -> None:
    """SPEC §6.1：每张租户表 INDEX(tenant_id, created_at DESC)。"""
    op.execute(
        f'CREATE INDEX IF NOT EXISTS "ix_{table}_tenant_created" '
        f'ON "{table}" (tenant_id, created_at DESC)'
    )
