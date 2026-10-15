"""端到端：跨租户 404 语义（SPEC §4.4 / AC-13）。

铁律：跨租户访问返回 404 而非 403——403 会泄露资源存在性形成枚举 oracle。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from tests.conftest import DB_REACHABLE

pytestmark = pytest.mark.skipif(
    not DB_REACHABLE, reason="PostgreSQL 不可达，跳过跨租户语义测试（CI 必须提供）"
)


@pytest.fixture
def client(api_client: TestClient) -> TestClient:
    return api_client


def _register(client: TestClient, email: str) -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Str0ng-Pass-2026", "company_name": "测试公司"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_cross_tenant_member_access_returns_404_not_403(client: TestClient) -> None:
    """A 租户 owner 尝试改 B 租户成员的角色 → 404（不是 403）。"""
    a = _register(client, f"ta-{uuid.uuid4().hex[:8]}@example.com")
    b = _register(client, f"tb-{uuid.uuid4().hex[:8]}@example.com")

    a_token = a["tokens"]["access_token"]
    b_user_id = b["user"]["id"]

    resp = client.patch(
        f"/api/v1/tenants/current/members/{b_user_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {a_token}"},
    )
    assert resp.status_code == 404, f"跨租户必须 404，实际 {resp.status_code}: {resp.text}"
    assert resp.json()["code"] == 1004
    # 响应体不得包含「属于其他租户」类措辞
    assert "租户" not in resp.json()["message"]


def test_switch_to_foreign_tenant_returns_404(client: TestClient) -> None:
    """切换到非成员账套 → 404（与「账套不存在」不可区分）。"""
    a = _register(client, f"sw-{uuid.uuid4().hex[:8]}@example.com")
    b = _register(client, f"sw2-{uuid.uuid4().hex[:8]}@example.com")

    resp = client.post(
        "/api/v1/tenants/current/switch",
        json={"tenant_id": b["tenant"]["id"]},
        headers={"Authorization": f"Bearer {a['tokens']['access_token']}"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 1004


def test_invite_existing_member_conflicts(client: TestClient) -> None:
    """邀请自己（已是成员）→ 409，不泄露多余信息。"""
    a = _register(client, f"inv-{uuid.uuid4().hex[:8]}@example.com")
    resp = client.post(
        "/api/v1/tenants/current/members",
        json={"email": a["user"]["email"], "role": "admin"},
        headers={"Authorization": f"Bearer {a['tokens']['access_token']}"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 1005
