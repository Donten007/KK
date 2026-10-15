-- 开发环境数据库角色引导（dev bootstrap）。
-- 生产环境由运维按同一原则 provisioning：应用角色非 superuser 且无 BYPASSRLS
-- （SPEC §4.4 实现约束：超级用户绕过 RLS，代码评审硬规则）。
--
-- 用法（本地 dev）：
--   psql -U postgres -f scripts/bootstrap_dev_db.sql

-- 迁移角色：可 DDL（建表/建策略），不持有业务数据访问需求
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opc_migrate') THEN
        CREATE ROLE opc_migrate LOGIN PASSWORD 'opc_migrate_dev';
    END IF;
END
$$;

-- 应用角色：无超级用户、无 BYPASSRLS、无 CREATEROLE——RLS 对其强制生效
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opc_app') THEN
        CREATE ROLE opc_app LOGIN PASSWORD 'opc_app_dev' NOSUPERUSER NOCREATEROLE NOCREATEDB
            NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;

-- 连接与 schema 权限
GRANT CONNECT ON DATABASE opcagentai TO opc_app, opc_migrate;
GRANT USAGE ON SCHEMA public TO opc_app, opc_migrate;

-- 已存在对象（迁移前建的库）补权限
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO opc_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO opc_migrate;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO opc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO opc_migrate;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO opc_app, opc_migrate;
