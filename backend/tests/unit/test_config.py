"""单元测试：配置与 CORS（生产禁通配符）。"""

from __future__ import annotations

from app.config import Settings, get_settings


def test_cors_origins_include_frontend() -> None:
    settings = Settings(frontend_origin="https://app.example.com", app_url="https://api.example.com")
    origins = settings.cors_origins
    assert "https://app.example.com" in origins
    assert "*" not in origins


def test_cors_origins_dev_includes_localhost() -> None:
    settings = Settings(app_env="development", frontend_origin="http://localhost:5173")
    assert "http://localhost:5173" in settings.cors_origins
    assert "http://127.0.0.1:5173" in settings.cors_origins


def test_jwt_secret_min_length() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short")


def test_defaults_match_spec() -> None:
    settings = get_settings()
    assert settings.jwt_access_ttl_seconds == 900  # 15min
    assert settings.jwt_refresh_ttl_seconds == 604800  # 7d
    assert "OPCAgentAI/" in settings.crawler_user_agent  # G3 UA 声明
