"""应用配置加载。所有配置从环境变量注入，业务代码禁止散落硬编码连接串/密钥。"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """运行期配置。字段名与 .env.example 一一对应。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Environment = "development"
    app_debug: bool = False
    app_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://opc_app:opc_app_dev@localhost:5432/opcagentai"
    database_migration_url: str = (
        "postgresql+asyncpg://opc_migrate:opc_migrate_dev@localhost:5432/opcagentai"
    )
    db_pool_size: int = Field(default=20, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=30, ge=1)
    db_statement_timeout_ms: int = Field(default=15000, ge=100)

    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-insecure-secret-change-me-32bytes"
    jwt_access_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    jwt_refresh_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)

    rate_limit_enabled: bool = True

    crawler_user_agent: str = (
        "OPCAgentAI/1.0 (+https://opcagentai.com/bot; contact=ops@opcagentai.com)"
    )

    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("jwt_secret")
    @classmethod
    def _secret_must_be_long_enough(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET 长度必须 >= 32 字符")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        """CORS 白名单。生产环境禁止通配符（SPEC §4.5 安全注意事项）。"""
        origins = {self.frontend_origin, self.app_url}
        if not self.is_production:
            origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})
        return sorted(o for o in origins if o)


@lru_cache
def get_settings() -> Settings:
    """进程内单例。测试通过清除缓存注入不同配置。"""
    return Settings()
