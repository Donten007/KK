"""认证相关请求/响应 schema（对齐 openapi.yaml /api/v1/auth/*）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """邮箱注册。注册成功后自动创建首个账套并签发该账套作用域的 token。"""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    name: str | None = None
    created_at: datetime


class TenantOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    plan: str
    status: str
    created_at: datetime


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    # openapi TokenPair 未声明的补充字段：refresh 过期绝对时间，
    # 供前端展示「7 天内免登录」与本地过期判断（SPEC §12.3 断言读取该字段）
    refresh_expires_at: datetime


class AuthResultOut(BaseModel):
    user: UserOut
    tenant: TenantOut
    tokens: TokenPairOut
