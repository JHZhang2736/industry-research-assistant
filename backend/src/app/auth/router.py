"""认证路由：注册 / 登录 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import ActiveUserDep, DbDep
from app.auth.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.auth.security import create_access_token
from app.auth.service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    authenticate,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册新用户并返回 access token",
)
async def register(payload: RegisterIn, db: DbDep) -> TokenOut:
    try:
        user = await register_user(
            db,
            username=payload.username,
            email=payload.email,
            password=payload.password,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    token, expires_in = create_access_token(subject=str(user.id))
    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenOut,
    summary="用户名或邮箱 + 密码登录",
)
async def login(payload: LoginIn, db: DbDep) -> TokenOut:
    try:
        user = await authenticate(db, account=payload.account, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        ) from exc

    token, expires_in = create_access_token(subject=str(user.id))
    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="获取当前登录用户信息",
)
async def me(user: ActiveUserDep) -> UserOut:
    return UserOut.model_validate(user)
