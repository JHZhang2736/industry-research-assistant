"""认证业务逻辑层。

把 ORM 操作、密码哈希、错误归一化收敛在这一层，路由层只负责 HTTP 适配。
错误用自定义异常表达，路由层捕获后转成对应的 HTTPException。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.models.user import User


class AuthError(Exception):
    """认证模块业务异常基类。"""


class UserAlreadyExistsError(AuthError):
    """用户名或邮箱已被占用。"""


class InvalidCredentialsError(AuthError):
    """登录失败：账号不存在 / 密码错误 / 账号被禁用 —— 统一一个错误，防枚举。"""


async def register_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
) -> User:
    """创建新用户。

    并发安全：依赖 username/email 的 UNIQUE 约束兜底；
    应用层先查一次只是为了拿到更友好的错误，真正的 race condition 仍由 DB 拦截。
    """
    normalized_username = username.lower()
    normalized_email = email.lower()

    stmt = select(User).where(
        or_(User.username == normalized_username, User.email == normalized_email)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise UserAlreadyExistsError(
            "username already taken"
            if existing.username == normalized_username
            else "email already registered"
        )

    user = User(
        username=normalized_username,
        email=normalized_email,
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise UserAlreadyExistsError("username or email already taken") from exc
    await db.refresh(user)
    return user


async def authenticate(
    db: AsyncSession,
    *,
    account: str,
    password: str,
) -> User:
    """验证账号密码。

    account 既可以是 username 也可以是 email；统一 lower 比对。
    任何失败一律抛 InvalidCredentialsError，**不区分**用户不存在 vs 密码错，防枚举。
    """
    normalized = account.lower()
    stmt = select(User).where(or_(User.username == normalized, User.email == normalized))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        # 仍然跑一次 verify_password 让响应时间与"用户存在但密码错"接近，进一步抗时序攻击
        verify_password(password, "$2b$12$" + "x" * 53)
        raise InvalidCredentialsError("invalid credentials")
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError("invalid credentials")
    if not user.is_active:
        raise InvalidCredentialsError("invalid credentials")
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)
