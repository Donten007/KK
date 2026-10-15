# OPCAgentAI 前端镜像（多阶段构建，Next.js 16 standalone 输出）
#
# 【构建上下文 = 仓库根，不是 frontend/】
# 原因：设计 Token 唯一来源是 design-system/design-tokens.css（设计师产出，
# 刻意不复制进前端，globals.css 以 ../../../design-system/ 相对路径引用）。
# 若上下文仅 frontend/，Token 文件不在构建上下文内，build 直接失败。
#
# 正确构建命令（本地与云托管 buildStrategy=cloud 通用）：
#   docker build -f frontend/Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=<后端公网域名> -t frontend .
# （注意末尾的 "." 是仓库根）

# ---- 构建阶段 ----
FROM node:22-bookworm-slim AS builder

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /build

# 先拷贝依赖清单装依赖，利用 Docker 层缓存
COPY frontend/package.json frontend/package-lock.json ./frontend/
WORKDIR /build/frontend
RUN npm ci

# 拷贝源码 + 设计 Token（相对路径 ../../../design-system/ 的唯一来源）
WORKDIR /build
COPY frontend/ ./frontend/
COPY design-system/ ./design-system/

# NEXT_PUBLIC_* 变量在构建时内联进产物，必须经 build arg 注入。
# 缺省值仅为本地镜像验证占位，生产构建必须传真实后端公网域名。
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

WORKDIR /build/frontend
RUN npm run build

# ---- 运行时阶段：standalone 自包含产物，非 root 运行 ----
FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
USER appuser

# standalone 产物含精简 node_modules 与 server.js（outputFileTracingRoot=仓库根，
# 产物内应用相对根目录嵌套在 frontend/ 子目录下）
COPY --from=builder --chown=appuser:appuser /build/frontend/.next/standalone ./
COPY --from=builder --chown=appuser:appuser /build/frontend/.next/static ./frontend/.next/static

# standalone 的 server.js 以 PORT 环境变量驱动监听端口（云托管注入 PORT）
EXPOSE 3000
CMD ["node", "frontend/server.js"]
