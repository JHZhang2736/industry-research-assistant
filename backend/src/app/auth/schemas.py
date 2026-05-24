"""认证模块 Pydantic schemas。

命名约定：
- `*In` 表示请求体
- `*Out` 表示响应体
- 任何场景都**不暴露 hashed_password**
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        if not USERNAME_PATTERN.match(v):
            raise ValueError("username 仅允许字母、数字、下划线、连字符")
        return v.lower()

    @field_validator("password")
    @classmethod
    def _validate_password_strength(cls, v: str) -> str:
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("密码必须同时包含字母和数字")
        return v


class LoginIn(BaseModel):
    """登录入参。account 可以是 username 或 email，由 service 层判别。"""

    account: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="token 有效期，秒")
    user: UserOut
