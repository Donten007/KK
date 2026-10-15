"""密码哈希与 JWT 签发/校验（SPEC §4.3 锁定）。

- 密码哈希：argon2-cffi，禁止 bcrypt
- Access Token：JWT，15 分钟
- Refresh Token：JWT（typ=refresh），7 天；哈希落库，rotation 每次轮换，
  检测到旧 token 复用（重放）→ 吊销该用户全部 refresh token 并记安全日志
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from app.config import get_settings
from app.core.errors import UnauthenticatedError
from app.core.logging import get_logger
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

logger = get_logger("security")

TokenType = Literal["access", "refresh"]

# argon2 参数：OWASP 推荐量级（m=19456(19MiB), t=2, p=1）。调高前先测 P95 影响。
_argon2 = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

_ALGORITHM = "HS256"


# ---- 密码 ----

def hash_password(plain: str) -> str:
    return _argon2.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _argon2.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


def password_needs_rehash(hashed: str) -> bool:
    """参数升级后平滑迁移：下次登录成功时重哈希。"""
    try:
        return _argon2.check_needs_rehash(hashed)
    except Exception:
        return True


# ---- Refresh Token 哈希（明文不落库，SPEC §4.3）----

def hash_refresh_token(token: str) -> str:
    """SHA-256 十六进制。refresh token 是高熵 JWT，无需慢哈希；
    慢哈希在这里只会拖垮 refresh 端点且不增加安全性（无字典空间）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---- JWT ----

def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    issued = _now()
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "typ": "access",
        "iat": issued,
        "exp": issued + timedelta(seconds=settings.jwt_access_ttl_seconds),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def create_refresh_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, token_id: uuid.UUID) -> str:
    """token_id 即 auth_refresh_tokens 行主键，rotation 时定位旧行。"""
    settings = get_settings()
    issued = _now()
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "jti": str(token_id),
        "typ": "refresh",
        "iat": issued,
        "exp": issued + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """校验签名与类型。失败一律抛 UnauthenticatedError（1002），不区分原因。"""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[_ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthenticatedError() from exc

    if payload.get("typ") != expected_type:
        # 拿 refresh token 当 access token 用（或反之）→ 按未认证处理
        raise UnauthenticatedError()
    return payload


def refresh_expires_at(token: str) -> datetime:
    payload = decode_token(token, expected_type="refresh")
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise UnauthenticatedError()
    return datetime.fromtimestamp(exp, tz=UTC)
