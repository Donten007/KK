"""每租户独立解密密钥（DEK）的包裹/解包（AC-15）。

结构：
- KEK（Key Encryption Key）：平台主密钥，来自环境变量 CREDENTIAL_KEK（base64, 32 字节），
  生产必须由 KMS/密钥管理注入，禁止进镜像与代码库
- DEK（Data Encryption Key）：每租户随机生成，用 KEK 经 AES-256-GCM 包裹后
  以 base64 存 tenants.tenant_dek；明文 DEK 只在内存中短暂存在

爆炸半径控制：攻击者拿到单个租户的密文 + 数据库，无 KEK 无法解包 DEK，
从而无法解密该租户凭据；即使某租户 DEK 泄露，其他租户不受影响（AC-15）。
"""

from __future__ import annotations

import base64
import os

from app.core.errors import BusinessError, ErrorCode
from app.core.logging import get_logger
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = get_logger("crypto")

_KEK_ENV = "CREDENTIAL_KEK"
_KEK_BYTES = 32  # AES-256


class CredentialCryptoError(BusinessError):
    def __init__(self, message: str = "密钥服务不可用") -> None:
        super().__init__(ErrorCode.INTERNAL_ERROR, message)


def _load_kek() -> bytes:
    raw = os.environ.get(_KEK_ENV, "").strip()
    if not raw:
        raise CredentialCryptoError("CREDENTIAL_KEK 未配置：拒绝以明文形态处理凭据")
    try:
        kek = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise CredentialCryptoError("CREDENTIAL_KEK 格式无效（应为 base64）") from exc
    if len(kek) != _KEK_BYTES:
        raise CredentialCryptoError(f"CREDENTIAL_KEK 长度必须为 {_KEK_BYTES} 字节")
    return kek


def generate_dek() -> bytes:
    """生成租户 DEK 明文（仅内存中短暂存在，调用方立即包裹后丢弃）。"""
    return AESGCM.generate_key(bit_length=256)


def wrap_dek(dek: bytes) -> str:
    """DEK → base64(nonce || ciphertext)。nonce 12 字节随机，每次包裹不同。"""
    kek = _load_kek()
    nonce = os.urandom(12)
    ciphertext = AESGCM(kek).encrypt(nonce, dek, None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def unwrap_dek(wrapped_b64: str) -> bytes:
    """base64(nonce || ciphertext) → DEK 明文。KEK 错误或密文损坏即抛错。"""
    kek = _load_kek()
    try:
        blob = base64.b64decode(wrapped_b64, validate=True)
        nonce, ciphertext = blob[:12], blob[12:]
        return AESGCM(kek).decrypt(nonce, ciphertext, None)
    except (InvalidTag, ValueError) as exc:
        # 不解包细节进日志（可能含密文片段），只记事件
        logger.warning("dek_unwrap_failed", tag="dek_unwrap_failed")
        raise CredentialCryptoError("解密密钥解包失败") from exc
