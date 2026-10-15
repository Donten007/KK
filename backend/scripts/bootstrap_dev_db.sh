#!/usr/bin/env bash
# 本地/开发用的一键环境引导：建库、建角色、授权、跑迁移。
# CI 用同样的步骤（见 .github/workflows 的 db-service + bootstrap 段）。
#
# 用法：
#   export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGPASSWORD=postgres
#   bash scripts/bootstrap_dev_db.sh
set -euo pipefail

DB_NAME="${DB_NAME:-opcagentai_test}"
PSQL=(psql -v ON_ERROR_STOP=1)

echo "[1/4] 建数据库 ${DB_NAME}"
"${PSQL[@]}" -d postgres <<SQL
SELECT 'CREATE DATABASE ${DB_NAME}'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

echo "[2/4] 建角色（非 superuser、无 BYPASSRLS）"
"${PSQL[@]}" -d "${DB_NAME}" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opc_app') THEN
        CREATE ROLE opc_app LOGIN PASSWORD 'opc_app_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opc_migrate') THEN
        CREATE ROLE opc_migrate LOGIN PASSWORD 'opc_migrate_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
ALTER DATABASE opcagentai_test OWNER TO opc_migrate;
GRANT CONNECT ON DATABASE opcagentai_test TO opc_app, opc_migrate;
GRANT USAGE ON SCHEMA public TO opc_app, opc_migrate;
SQL

echo "[3/4] Alembic 迁移（先建表，授权必须在表存在之后 —— CI 全新库曾因顺序反了报 audit_logs 不存在）"
DATABASE_MIGRATION_URL="${DATABASE_MIGRATION_URL:-postgresql+asyncpg://opc_migrate:opc_migrate_dev@${PGHOST:-127.0.0.1}:${PGPORT:-5432}/${DB_NAME}}" \
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://opc_app:opc_app_dev@${PGHOST:-127.0.0.1}:${PGPORT:-5432}/${DB_NAME}}" \
JWT_SECRET="${JWT_SECRET:-test-secret-test-secret-test-secret-32}" \
CREDENTIAL_KEK="${CREDENTIAL_KEK:-dGVzdC10ZXN0LXRlc3QtdGVzdC10ZXN0LXRlc3QtdGVzdDEyMzQ1Njc4OTA=}" \
python -m alembic upgrade head

echo "[4/4] 授权（应用角色只 DML，审计表 append-only）"
"${PSQL[@]}" -d "${DB_NAME}" <<'SQL'
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO opc_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO opc_migrate;
ALTER DEFAULT PRIVILEGES FOR ROLE opc_migrate IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO opc_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO opc_app, opc_migrate;
REVOKE UPDATE, DELETE ON audit_logs FROM opc_app;
SQL

echo "[OK] 环境就绪：${DB_NAME}"