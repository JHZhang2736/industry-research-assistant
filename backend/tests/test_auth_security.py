"""security 模块单测：哈希与 JWT 编解码。"""

from __future__ import annotations

import time

import jwt
import pytest

from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_returns_distinct_outputs_for_same_input() -> None:
    h1 = hash_password("hunter2abc")
    h2 = hash_password("hunter2abc")
    assert h1 != h2  # 不同 salt
    assert verify_password("hunter2abc", h1)
    assert verify_password("hunter2abc", h2)


def test_verify_password_rejects_wrong_password() -> None:
    h = hash_password("correctpw123")
    assert not verify_password("wrongpw123", h)


def test_verify_password_handles_invalid_hash_gracefully() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_round_trip() -> None:
    token, expires_in = create_access_token(subject="user-123")
    assert expires_in > 0
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["typ"] == "access"
    assert "exp" in payload and "iat" in payload


def test_decode_expired_token_raises() -> None:
    # 直接签一个已经过期的 token
    from app.core.config import get_settings

    s = get_settings()
    expired = jwt.encode(
        {
            "sub": "u",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
            "typ": "access",
        },
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_decode_wrong_type_rejected() -> None:
    from app.core.config import get_settings

    s = get_settings()
    wrong_type = jwt.encode(
        {"sub": "u", "iat": int(time.time()), "exp": int(time.time()) + 3600, "typ": "refresh"},
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(wrong_type)


def test_decode_tampered_signature_rejected() -> None:
    token, _ = create_access_token(subject="user-1")
    # 篡改最后一个字符
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered)
