"""认证服务：注册 / 登录 / refresh rotation / 登出。

事务边界设计（关键）：
- register 用**单个事务**完成 user + tenant + member + link + refresh_token：
  tenant GUC 在新租户 id 生成后即可设置（GUC 只是字符串，不要求租户行已存在），
  从而 member 的 RLS WITH CHECK 在同一事务内通过——注册失败不留孤儿数据。
- login/refresh 用 tenant_transaction（RLS 上下文随事务设置，连接池复用不泄漏）。

安全语义：
- 登录失败不区分「邮箱不存在」与「密码错误」（防用户枚举）
- refresh 旧 token 复用（重放）→ 吊销该用户本租户全部 refresh token + WARNING 安全日志
- refresh token 只存 SHA-256 哈希，明文不落库
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.core.crypto import generate_dek, wrap_dek
from app.core.errors import ConflictError, UnauthenticatedError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.db.rls import tenant_scope, tenant_transaction, work_unit
from app.models.user import RefreshToken, User
from app.repositories.audit_repo import AuditLogRepository
from app.repositories.tenant_link_repo import UserTenantLinkRepository
from app.repositories.tenant_repo import TenantMemberRepository, TenantRepository
from app.repositories.user_repo import RefreshTokenRepository, UserRepository
from app.schemas.auth import AuthResultOut, TokenPairOut
from app.utils.ids import generate_tenant_code
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("auth")

_MAX_CODE_ATTEMPTS = 5


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tenants = TenantRepository(session)
        self.members = TenantMemberRepository(session)
        self.links = UserTenantLinkRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.audit = AuditLogRepository(session)

    # ---- 注册 ----

    async def register(self, *, email: str, password: str, company_name: str | None) -> AuthResultOut:
        existing = await self.users.get_by_email(email)
        if existing is not None:
            raise ConflictError("该邮箱已注册，请直接登录")

        code = await self._fresh_tenant_code()
        now = datetime.now(UTC)

        async with work_unit(self.session):
            user = await self.users.create(
                email=email, password_hash=hash_password(password), name=None
            )
            tenant = await self.tenants.create(
                code=code,
                name=(company_name or email.split("@", 1)[0])[:200],
                tenant_dek=wrap_dek(generate_dek()),
            )
            # 新租户上下文：GUC 不要求租户行已存在，同事务内 member 的 WITH CHECK 即可通过
            async with tenant_scope(self.session, tenant.id):
                await self.members.add_member(
                    tenant_id=tenant.id, user_id=user.id, role="owner"
                )
                await self.links.add(user_id=user.id, tenant_id=tenant.id, role="owner")
                await self.users.set_last_tenant(user.id, tenant.id)
                token_row, refresh_token = await self._issue_refresh_pair(
                    tenant_id=tenant.id, user_id=user.id, expires_at=now + timedelta(days=7)
                )
                await self.audit.record(
                    tenant_id=tenant.id,
                    event_type="signup_complete",
                    actor_id=user.id,
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                )

        return await self._build_auth_result(user, tenant.id, token_row, refresh_token)

    # ---- 登录 ----

    async def login(self, *, email: str, password: str) -> AuthResultOut:
        user = await self.users.get_by_email(email)
        # 统一文案：不泄露「邮箱是否存在」
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthenticatedError("邮箱或密码不正确")

        resolved = await self.links.resolve_login_tenant(
            user_id=user.id, last_tenant_id=user.last_tenant_id
        )
        if resolved is None:
            raise UnauthenticatedError("当前账号没有可访问的账套，请联系客户经理")
        tenant_id, _role = resolved

        now = datetime.now(UTC)
        async with tenant_transaction(self.session, tenant_id):
            token_row, refresh_token = await self._issue_refresh_pair(
                tenant_id=tenant_id, user_id=user.id, expires_at=now + timedelta(days=7)
            )
            if user.last_tenant_id != tenant_id:
                await self.users.set_last_tenant(user.id, tenant_id)
            # 参数升级后的密码哈希在登录成功时平滑迁移
            if password_needs_rehash(user.password_hash):
                await self.users.update_password_hash(user.id, hash_password(password))

        return await self._build_auth_result(user, tenant_id, token_row, refresh_token)

    # ---- refresh rotation ----

    async def refresh(self, *, refresh_token: str) -> TokenPairOut:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
        token_id = uuid.UUID(payload["jti"])
        token_hash = hash_refresh_token(refresh_token)
        now = datetime.now(UTC)

        # 【需资深】重放分支必须「先提交吊销、再抛错」：
        # 若在事务块内 raise，work_unit 退出时回滚，吊销与审计日志一并消失——
        # 安全动作被自己的异常回滚掉（本次实测踩到：重放后 token 仍可用）。
        # 因此分支只置标志，事务提交后再抛。
        replay_detected = False
        link_role = ""
        new_row: RefreshToken | None = None
        new_token = ""

        async with tenant_transaction(self.session, tenant_id):
            row = await self.refresh_tokens.get_any_by_hash(
                tenant_id=tenant_id, token_hash=token_hash
            )
            if row is None:
                raise UnauthenticatedError("登录状态已失效，请重新登录")

            if row.revoked_at is not None:
                # 重放检测：已轮换/吊销的 token 再次出现 → 吊销该用户本租户全部 token
                revoked = await self.refresh_tokens.revoke_all_for_user(
                    tenant_id=tenant_id, user_id=user_id
                )
                await self.audit.record(
                    tenant_id=tenant_id,
                    event_type="refresh_token_reuse_detected",
                    level="warning",
                    actor_id=user_id,
                    resource_type="auth_refresh_tokens",
                    resource_id=str(token_id),
                    result="denied",
                    detail={"revoked_count": revoked},
                )
                replay_detected = True
            elif row.expires_at <= now:
                raise UnauthenticatedError("登录已过期，请重新登录")
            else:
                # 用户可能已被移出该账套：link 不存在即拒绝续期
                link = await self.links.get(user_id=user_id, tenant_id=tenant_id)
                if link is None:
                    raise UnauthenticatedError("你已不在该账套，请重新登录")
                link_role = link.role
                new_row, new_token = await self._issue_refresh_pair(
                    tenant_id=tenant_id, user_id=user_id, expires_at=now + timedelta(days=7)
                )
                await self.refresh_tokens.revoke(row_id=row.id, replaced_by=new_row.id)

        if replay_detected:
            logger.warning(
                "refresh_token_reuse_detected",
                tag="refresh_token_reuse_detected",
                tenant_id=str(tenant_id),
                user_id=str(user_id),
            )
            raise UnauthenticatedError("登录状态已失效，请重新登录")

        assert new_row is not None and new_token  # 正常轮换路径必然赋值
        access = create_access_token(user_id=user_id, tenant_id=tenant_id, role=link_role)
        return TokenPairOut(
            access_token=access,
            refresh_token=new_token,
            expires_in=get_settings().jwt_access_ttl_seconds,
            refresh_expires_at=new_row.expires_at,
        )

    # ---- 登出 ----

    async def logout(self, *, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except UnauthenticatedError:
            return  # 幂等：token 本就无效时静默成功
        tenant_id = uuid.UUID(payload["tenant_id"])
        token_hash = hash_refresh_token(refresh_token)
        async with tenant_transaction(self.session, tenant_id):
            await self.refresh_tokens.revoke_by_hash(tenant_id=tenant_id, token_hash=token_hash)

    # ---- 内部 ----

    async def _fresh_tenant_code(self) -> str:
        for _ in range(_MAX_CODE_ATTEMPTS):
            code = generate_tenant_code()
            if not await self.tenants.code_exists(code):
                return code
        raise ConflictError("账套号生成冲突，请重试")

    async def _issue_refresh_pair(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, expires_at: datetime
    ) -> tuple[RefreshToken, str]:
        """签发 refresh token：token_id（= JWT jti = 行主键）一次生成，
        JWT 与存储哈希同源——避免「行 id 与 jti 不一致导致首刷即失效」。
        调用方负责事务上下文。返回 (行, 明文 token)。"""
        token_id = uuid.uuid4()
        token = create_refresh_token(user_id=user_id, tenant_id=tenant_id, token_id=token_id)
        row = await self.refresh_tokens.create(
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            expires_at=expires_at,
            row_id=token_id,
        )
        return row, token

    async def _build_auth_result(
        self, user: User, tenant_id: uuid.UUID, token_row: RefreshToken, refresh_token: str
    ) -> AuthResultOut:
        tenant = await self.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise UnauthenticatedError()
        link = await self.links.get(user_id=user.id, tenant_id=tenant_id)
        role = link.role if link is not None else "member"
        access = create_access_token(user_id=user.id, tenant_id=tenant_id, role=role)
        return AuthResultOut(
            user=user,
            tenant=tenant,
            tokens=TokenPairOut(
                access_token=access,
                refresh_token=refresh_token,
                expires_in=get_settings().jwt_access_ttl_seconds,
                refresh_expires_at=token_row.expires_at,
            ),
        )
