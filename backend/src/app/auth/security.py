"""密码哈希与 JWT 编解码工具。

设计要点：
- bcrypt：成本因子从配置读，测试场景可以调低加速；输出/输入都是 str
  （bcrypt 库本身只接受 bytes，这里封一层免去业务侧到处 encode/decode）
- JWT：HS256 对称签名，单服务足够；claims 包含 sub/exp/iat/typ；
  解码异常统一抛 `InvalidTokenError`（pyjwt 的父类），路由层捕获后转 401
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希；返回带盐的完整哈希串。"""
    settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码是否匹配哈希。bcrypt.checkpw 自带恒定时间比较，抗时序攻击。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # hashed 不是合法 bcrypt 串（数据损坏 / 历史脏数据），视作密码错误
        return False


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> tuple[str, int]:
    """签发 access token。

    Returns:
        (token, expires_in_seconds)：业务侧把 expires_in 透给前端，前端据此提前刷新
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "typ": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_access_ttl_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    """解码并校验 access token。

    Raises:
        jwt.PyJWTError 的具体子类（ExpiredSignatureError / InvalidTokenError 等）
    """
    settings = get_settings()
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("token type mismatch")
    return payload
