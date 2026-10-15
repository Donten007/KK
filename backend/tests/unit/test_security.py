"""单元测试：安全原语（argon2 / JWT / refresh hash）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.core.errors import UnauthenticatedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    hashed = hash_password("Str0ng-Pass-2026")
    assert hashed != "Str0ng-Pass-2026"
    assert hashed.startswith("$argon2")  # 禁止 bcrypt 的可观测证据
    assert verify_password("Str0ng-Pass-2026", hashed)
    assert not verify_password("wrong-pass", hashed)


def test_access_token_roundtrip_and_claims() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="owner")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "owner"
    assert payload["typ"] == "access"


def test_access_token_ttl_is_15_minutes() -> None:
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="member")
    payload = decode_token(token, expected_type="access")
    ttl = payload["exp"] - payload["iat"]
    assert 850 <= ttl <= 900, f"access token TTL 应约 900s，实际 {ttl}"


def test_refresh_token_ttl_is_7_days() -> None:
    token = create_refresh_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), token_id=uuid.uuid4()
    )
    payload = decode_token(token, expected_type="refresh")
    ttl = payload["exp"] - payload["iat"]
    assert 604000 <= ttl <= 604800, f"refresh token TTL 应约 7 天，实际 {ttl}"


def test_token_type_confusion_rejected() -> None:
    """refresh token 当 access token 用必须拒绝（typ 校验）。"""
    refresh = create_refresh_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), token_id=uuid.uuid4()
    )
    with pytest.raises(UnauthenticatedError):
        decode_token(refresh, expected_type="access")
    access = create_access_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="member"
    )
    with pytest.raises(UnauthenticatedError):
        decode_token(access, expected_type="refresh")


def test_expired_token_rejected() -> None:
    from app.config import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "member",
        "typ": "access",
        "iat": now - timedelta(seconds=100),
        "exp": now - timedelta(seconds=1),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(UnauthenticatedError):
        decode_token(token, expected_type="access")


def test_wrong_secret_rejected() -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "member",
        "typ": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
    }
    token = jwt.encode(payload, "attacker-secret-attacker-secret-32", algorithm="HS256")
    with pytest.raises(UnauthenticatedError):
        decode_token(token, expected_type="access")


def test_refresh_token_hash_is_deterministic_hex64() -> None:
    token = "sample-refresh-token"
    h1 = hash_refresh_token(token)
    h2 = hash_refresh_token(token)
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)  # 必须是 hex
