"""端到端：认证流（注册 → 登录 → me → refresh rotation → 重放检测 → 登出）。

断言依据：SPEC §12.2 / §12.3 / §4.3（rotation 与重放检测）。
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from tests.conftest import DB_REACHABLE

pytestmark = pytest.mark.skipif(
    not DB_REACHABLE, reason="PostgreSQL 不可达，跳过端到端认证测试（CI 必须提供）"
)

_CODE_RE = re.compile(r"^AC-[0-9A-Z]{8}$")


@pytest.fixture
def client(api_client: TestClient) -> TestClient:
    return api_client


def _register(client: TestClient, email: str, password: str = "Str0ng-Pass-2026") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "company_name": "测试公司"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == 0
    return body["data"]


def test_register_creates_tenant_and_tokens(client: TestClient) -> None:
    email = f"boss-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)

    assert _CODE_RE.match(data["tenant"]["code"]), "账套号格式应为 AC-XXXXXXXX"
    assert data["tenant"]["id"] != data["tenant"]["code"], "tenant_id 与 code 职责分离"
    assert data["user"]["email"] == email
    # 响应绝不包含密码哈希（SPEC §12.2 断言）
    assert "password_hash" not in data["user"]
    assert data["tokens"]["token_type"] == "Bearer"
    assert data["tokens"]["expires_in"] == 900


def test_register_duplicate_email_conflicts(client: TestClient) -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    _register(client, email)
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Str0ng-Pass-2026"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 1005


def test_login_wrong_password_does_not_leak_existence(client: TestClient) -> None:
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    _register(client, email)
    # 错密码
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "Wrong-Pass-999"})
    assert resp.status_code == 401
    # 不存在的邮箱：同一状态码与文案（防用户枚举）
    resp2 = client.post(
        "/api/v1/auth/login",
        json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": "Wrong-Pass-999"},
    )
    assert resp2.status_code == 401
    assert resp2.json()["message"] == resp.json()["message"]


def test_me_returns_current_user(client: TestClient) -> None:
    email = f"me-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)
    token = data["tokens"]["access_token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == email
    assert "password_hash" not in resp.json()["data"]


def test_me_without_token_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


def test_refresh_rotation_invalidates_old_token(client: TestClient) -> None:
    email = f"rot-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)
    old_refresh = data["tokens"]["refresh_token"]

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_refresh = resp.json()["data"]["refresh_token"]
    assert new_refresh != old_refresh, "refresh 必须轮换"

    # 旧 token 立即失效
    resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp2.status_code == 401


def test_refresh_replay_revokes_all_tokens(client: TestClient) -> None:
    """重放检测：已轮换的 refresh 再次出现 → 该用户本租户全部 token 吊销。"""
    email = f"replay-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)
    r1 = data["tokens"]["refresh_token"]

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    r2 = resp.json()["data"]["refresh_token"]
    assert r2 != r1

    # 重放 r1 → 401
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert replay.status_code == 401

    # 连带后果：r2 也被吊销（重放即视为泄露）
    resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": r2})
    assert resp2.status_code == 401


def test_logout_revokes_refresh(client: TestClient) -> None:
    email = f"out-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)
    refresh = data["tokens"]["refresh_token"]

    resp = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 200

    resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp2.status_code == 401


def test_access_token_as_refresh_rejected(client: TestClient) -> None:
    email = f"mix-{uuid.uuid4().hex[:8]}@example.com"
    data = _register(client, email)
    resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": data["tokens"]["access_token"]}
    )
    assert resp.status_code == 401
