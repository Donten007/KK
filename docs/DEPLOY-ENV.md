# DEPLOY-ENV 生产环境变量清单

平台：腾讯云 CloudBase 云托管（CloudRun 容器）
环境：hechalema-d4gbb8sal44ec8f68（ap-shanghai）
数据库：CloudBase PostgreSQL 17.11（SQLAlchemy + asyncpg + Alembic）

> 敏感值（密钥/连接串密码）部署时经云托管「环境变量配置」注入，禁止写入版本库。
> 本清单值均为占位符，`***` 处由负责人在部署时填入真实值。

## 一、后端服务（CloudRun 服务 envParams）

来源基线：`backend/.env.example` 与 `backend/app/config.py`（pydantic-settings，字段名 = 环境变量名）。

### 必配

| 变量 | 值（占位） | 说明 |
|------|-----------|------|
| DATABASE_URL | `postgresql+asyncpg://opcadmin:***@<PG内网地址>:5432/postgres` | 应用连接串。主机用 CloudBase PG 控制台「网络配置」的内网地址；驱动前缀必须是 `postgresql+asyncpg://` |
| DATABASE_MIGRATION_URL | `postgresql+asyncpg://opcadmin:***@<PG内网地址>:5432/postgres` | 迁移连接（需 DDL 权限，`alembic upgrade head` 使用，见 migrations/env.py） |
| JWT_SECRET | `<openssl rand -base64 48>` | 长度必须 >= 32 字符（config.py 有校验，不满足启动即失败） |
| CREDENTIAL_KEK | `<base64(32字节)>` | 平台主密钥，包裹租户 DEK。生成：`python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`。**生成后必须离线备份，丢失 = 所有已存租户凭据不可解密** |
| APP_ENV | `production` | 开启生产模式（CORS 白名单收紧等） |
| FRONTEND_ORIGIN | `https://<前端云托管公网域名>` | CORS 白名单（生产禁止通配符） |
| APP_URL | `https://<后端云托管公网域名>` | 本站基址 |

### 强烈建议配置（有平台实例则必配）

| 变量 | 值（占位） | 说明 |
|------|-----------|------|
| REDIS_URL | `redis://<CloudBase Redis内网地址>:6379/0` | 限流/SSE 事件总线。未配置时限流 fail-open（SPEC 10.7），生产建议接真实 Redis |
| RATE_LIMIT_ENABLED | `true` | 限流总开关（生产必须 true） |

### 可选（不配则用代码默认值）

| 变量 | 默认 | 说明 |
|------|------|------|
| DB_POOL_SIZE | 20 | 单实例连接池；多实例部署时注意 PG 总连接数上限 |
| DB_MAX_OVERFLOW | 10 | 池溢出上限 |
| DB_STATEMENT_TIMEOUT_MS | 15000 | 语句超时 |
| JWT_ACCESS_TTL_SECONDS | 900 | access token 15 分钟 |
| JWT_REFRESH_TTL_SECONDS | 604800 | refresh token 7 天 |
| LOG_LEVEL | INFO | 生产不设 DEBUG |
| LOG_JSON | true | 生产建议 JSON 日志便于平台采集 |
| CRAWLER_USER_AGENT | 内置值 | 出网抓取 UA（不伪装浏览器） |
| APP_DEBUG | false | 生产必须 false |

### TCP 连库硬性要求：VPC 配置

后端容器访问 CloudBase PG 走**内网 TCP**，云托管部署时必须同时配置 **VpcConf**（`vpcId` + `subnetId`）：

1. 打开 CloudBase 控制台 -> PostgreSQL 实例 -> 「网络配置」；
2. 记录该 PG 实例所属的 **VPC ID 与子网 ID**，以及**内网连接地址**；
3. 云托管服务「服务设置 -> 网络」中选择同一 VPC / 子网（私有网络打通）；
4. `DATABASE_URL` 中主机填该**内网地址**，端口 5432。

禁止用 `127.0.0.1`、`localhost` 或占位符主机名部署 —— 容器内解析不到即启动失败。

## 二、前端服务（CloudRun 构建/运行变量）

| 变量 | 注入时机 | 值（占位） | 说明 |
|------|---------|-----------|------|
| NEXT_PUBLIC_API_BASE_URL | **构建时**（build arg 或 .env.production） | `https://<后端云托管公网域名>` | Next.js 对 `NEXT_PUBLIC_*` 在构建期内联进产物，运行期改环境变量无效 |
| PORT | 运行时（平台注入） | 平台分配 | standalone `server.js` 以 PORT 驱动监听端口 |

前端镜像构建命令（上下文 = 仓库根，Token 单一来源约束）：

```bash
docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://<后端域名> \
  -t frontend .
```

云托管 buildStrategy=cloud 时在「构建配置」中填写同样的 Dockerfile 路径与 build arg。

## 三、健康检查探针

| 端点 | 用途 | 依赖 |
|------|------|------|
| `GET /health` | 存活探针（liveness），云托管探活路径填这个 | 无 DB 依赖，DB 故障不影响 200 |
| `GET /health/ready` | 就绪探针（readiness） | 无 DB 依赖，仅报告进程状态 |

两者均返回 HTTP 200，响应体 `{"code":0,"data":{"status":"..."},"message":""}`。

## 四、部署与迁移流程要点

1. 数据库迁移：首次部署在容器内一次性任务执行 `alembic upgrade head`
   （镜像内已包含 alembic.ini 与 migrations/，连接串用 DATABASE_MIGRATION_URL）；
2. 后端镜像构建上下文 = `backend/` 目录（Dockerfile 在 backend/ 下）；
3. 前端镜像构建上下文 = **仓库根**（见 frontend/Dockerfile 头部注释）；
4. 回滚：云托管「版本历史」回退到上一版本镜像；数据库迁移为增量式，
   回滚版本前先确认无不可兼容的列删除（当前 8 个迁移均为增量建表/建策略）。
