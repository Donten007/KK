# OPCAgentAI 后端镜像（多阶段构建，CloudBase 云托管 CloudRun 适配）
# 构建上下文 = backend/ 目录：docker build -t backend ./backend
# 云托管场景 buildStrategy=cloud 时由平台在云端执行本文件，无需本地 Docker。

# ---- 构建阶段：安装精确锁定的 requirements 到独立 venv ----
FROM python:3.13-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY requirements.txt ./
# 生产镜像剔除 dev 门禁依赖（pytest/ruff/mypy/pip-audit 只进 CI，不进运行时）
# 精确锁定版本行原样保留，保证镜像依赖与 requirements.txt 完全一致。
RUN grep -v '^-r requirements-dev.txt' requirements.txt > requirements-prod.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements-prod.txt

# ---- 运行时阶段：只带 venv + 应用代码，非 root 运行 ----
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

# 非 root 用户（容器逃逸纵深防御）
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
USER appuser

# 应用代码
COPY --chown=appuser:appuser app/ ./app/
# 迁移入口（alembic.ini + migrations/ 保留在镜像内，便于部署流程以一次性任务
# 执行 `alembic upgrade head`；迁移连接角色由 DATABASE_MIGRATION_URL 注入）
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser migrations/ ./migrations/

# 云托管要求监听 0.0.0.0，端口跟随平台注入的 PORT，缺省 8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
