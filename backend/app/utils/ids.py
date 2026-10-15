"""纯工具函数（无业务、无副作用，code-organization 规范 §4 规则 6）。

账套号生成：AC- + 8 位 Crockford Base32（剔除 I/L/O/U 防口述误读），
8 × 5bit = 40 bit 熵，不可枚举（SPEC §4.4 / ADR-003）。
格式断言见 SPEC §12.2：grep -qE '^AC-[0-9A-Z]{8}$'
"""

from __future__ import annotations

import secrets
import uuid

# Crockford Base32 字母表：0-9 + A-Z 去掉 I/L/O/U
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LEN = 8
CODE_PREFIX = "AC-"


def generate_tenant_code() -> str:
    """生成一个账套号。唯一性由 TenantRepository.code_exists 重试保障。"""
    digits = "".join(secrets.choice(_CROCKFORD) for _ in range(_CODE_LEN))
    return f"{CODE_PREFIX}{digits}"


def is_valid_tenant_code(code: str) -> bool:
    if not code.startswith(CODE_PREFIX):
        return False
    body = code[len(CODE_PREFIX) :]
    return len(body) == _CODE_LEN and all(c in _CROCKFORD for c in body)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
